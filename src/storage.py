"""SQLite persistence layered onto the ORIGINAL Module 6 history schema.
The seed file is never overwritten. Runtime monitoring uses its own copy.
"""
from __future__ import annotations
import json
import shutil
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
SEED_DB = ROOT / 'data' / 'module6_sensor_history.db'
RUNTIME_DB = ROOT / 'state' / 'monitor.db'


def connect(db_path=RUNTIME_DB):
    conn = sqlite3.connect(str(db_path), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA busy_timeout=10000')
    conn.execute('PRAGMA journal_mode=WAL')
    return conn


def initialize(db_path=RUNTIME_DB, seed_path=SEED_DB):
    db_path, seed_path = Path(db_path), Path(seed_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if not db_path.exists():
        if not seed_path.exists() and seed_path.resolve() == SEED_DB.resolve():
            # Rebuild original Module 6 seed from untouched CSV if missing on clone.
            # Never regenerate or overwrite the working DB during app restart.
            from scripts.seed_history import main as regenerate_seed
            regenerate_seed()
        if seed_path.exists():
            # Only seed on first boot: never wipe accumulated history on restart.
            shutil.copy2(seed_path, db_path)
        else:
            db_path.touch()
    conn = connect(db_path)
    conn.execute('''CREATE TABLE IF NOT EXISTS readings (
      sensor TEXT NOT NULL, sample_number INTEGER NOT NULL, timestamp TEXT NOT NULL,
      raw_value REAL, accepted_value REAL, unit TEXT NOT NULL, status TEXT NOT NULL,
      decision TEXT NOT NULL, reason TEXT NOT NULL, timestamp_source TEXT NOT NULL,
      PRIMARY KEY(sensor,sample_number))''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_readings_sensor_time ON readings(sensor,timestamp)')
    cols = {r['name'] for r in conn.execute('PRAGMA table_info(readings)')}
    # Non-destructive extension of the original Module 6 readings schema.
    for name, dtype in [('source_timestamp', 'TEXT'), ('source_sample_number', 'INTEGER'),
                        ('captured_at_utc', 'TEXT'), ('origin', 'TEXT')]:
        if name not in cols:
            conn.execute(f'ALTER TABLE readings ADD COLUMN {name} {dtype}')
    conn.executescript('''
      CREATE TABLE IF NOT EXISTS monitor_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS monitor_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp_utc TEXT NOT NULL,
        event TEXT NOT NULL, detail TEXT NOT NULL);
      CREATE INDEX IF NOT EXISTS idx_readings_capture ON readings(sensor, captured_at_utc);
    ''')
    conn.commit()
    return conn


def meta_get(conn, key, default=None):
    row = conn.execute('SELECT value FROM monitor_meta WHERE key=?', (key,)).fetchone()
    return json.loads(row['value']) if row else default


def meta_set(conn, key, value):
    conn.execute('INSERT INTO monitor_meta(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                 (key, json.dumps(value)))


def insert_event(conn, event, detail, at=None):
    at = at or datetime.now(timezone.utc).isoformat(timespec='milliseconds')
    conn.execute('INSERT INTO monitor_events(timestamp_utc,event,detail) VALUES (?,?,?)',
                 (at, event, detail))
    conn.commit()


def insert_replay(conn, *, raw_value, status, decision, reason, source_timestamp,
                  source_sample_number, origin, timestamp, sensor='temperature', unit='C'):
    # New key, not Module 6's original sample_number. Source number separately retained.
    next_id = conn.execute('SELECT COALESCE(MAX(sample_number),0)+1 FROM readings WHERE sensor=?',
                           (sensor,)).fetchone()[0]
    value = raw_value if decision == 'ACCEPTED' else None
    conn.execute('''INSERT INTO readings
      (sensor, sample_number, timestamp, raw_value, accepted_value, unit,
       status, decision, reason, timestamp_source,
       source_timestamp, source_sample_number, captured_at_utc, origin)
       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
       (sensor, next_id, timestamp, raw_value, value, unit, status, decision, reason,
        'CLASSROOM_REPLAY_UTC', source_timestamp, source_sample_number, timestamp, origin))
    conn.commit()
    return next_id


def latest_replay(conn):
    return conn.execute('''SELECT * FROM readings WHERE sensor='temperature'
        AND captured_at_utc IS NOT NULL ORDER BY captured_at_utc DESC, sample_number DESC LIMIT 1''').fetchone()


def history(conn, limit=90, live_only=False, archive_only=False):
    """Select either replay arrivals or original Module 6 archive (never merge them)."""
    if live_only and archive_only:
        raise ValueError("history cannot be both replay and original")
    where = "WHERE sensor='temperature'"
    if live_only:
        where += " AND captured_at_utc IS NOT NULL"
    elif archive_only:
        where += " AND captured_at_utc IS NULL"
    return list(reversed(conn.execute(f'''SELECT timestamp,raw_value,accepted_value,status,decision,origin,
          source_timestamp FROM readings {where} ORDER BY timestamp DESC LIMIT ?''', (limit,)).fetchall()))


def total_counts(conn):
    all_rows = conn.execute("SELECT COUNT(*) FROM readings WHERE sensor='temperature'").fetchone()[0]
    live_rows = conn.execute("SELECT COUNT(*) FROM readings WHERE sensor='temperature' AND captured_at_utc IS NOT NULL").fetchone()[0]
    return {'historical': all_rows-live_rows, 'replayed': live_rows, 'total': all_rows}
