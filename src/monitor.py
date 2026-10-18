"""Replay worker: non-destructive Module 6 SQLite integration and health controls."""
from __future__ import annotations
import csv
import math
import threading
import time
from pathlib import Path
from datetime import datetime, timezone
from .storage import (ROOT,initialize,meta_get,meta_set,insert_event,insert_replay)
from .alerting import AlertEngine
from .eventlog import get_logger, log_event

CSV_PATH=ROOT/'data'/'module6_sample_sensor_history.csv'
PAUSE_FILE=ROOT/'state'/'pause.flag'


def source_rows(path=CSV_PATH):
    with open(path,newline='',encoding='utf-8') as f:
        return list(csv.DictReader(f))


def evaluate(raw, source_status):
    if raw in ('',None): return None,'MISSING','REJECTED','no numeric reading available'
    try: value=float(raw)
    except (ValueError,TypeError): return None,'INVALID','REJECTED','non-numeric reading'
    if not math.isfinite(value): return None,'INVALID','REJECTED','non-finite reading'
    if source_status != 'OK': return value,source_status,'REJECTED','source status not OK'
    if value < 0 or value > 50: return value,'OUT_OF_RANGE','REJECTED','outside 0-50 C accepted sensor range'
    return value,'OK','ACCEPTED','passed source and temperature-range validation'


def process_one(conn, sample, *, at=None, logger=None):
    """Sample is a (possibly test-injected) row; source timestamp remains unchanged."""
    at=at or datetime.now(timezone.utc).isoformat(timespec='milliseconds')
    raw, status, decision, reason=evaluate(sample.get('temperature_c'),sample.get('temperature_status','OK'))
    engine=AlertEngine.from_state(meta_get(conn,'alert_engine'))
    transition=engine.update(raw,decision=='ACCEPTED')
    meta_set(conn,'alert_engine',engine.serialize())
    origin=sample.get('origin','MODULE6_SOURCE_REPLAY')
    seq=insert_replay(conn, raw_value=raw,status=status,decision=decision,reason=reason,
          source_timestamp=sample.get('timestamp'),source_sample_number=sample.get('sample_number'),
          timestamp=at,origin=origin)
    if transition != 'NONE':
        name='ALERT_ACTIVATED' if transition=='ACTIVATED' else 'ALERT_CLEARED'
        detail=f'sample={seq} temperature={raw} threshold=30.0 clear=28.5'
        insert_event(conn,name,detail,at)
        if logger:log_event(logger,name,detail)
    name='READING_ACCEPTED' if decision=='ACCEPTED' else 'READING_REJECTED'
    detail=f'sample={seq} source={origin} status={status} raw={raw} reason={reason}'
    insert_event(conn,name,detail,at)
    if logger:log_event(logger,name,detail,'info' if decision=='ACCEPTED' else 'warning')
    if status=='MISSING':
        insert_event(conn,'MISSING_INPUT',f'sample={seq} no reading',at)
        if logger:log_event(logger,'MISSING_INPUT',f'sample={seq} no reading','warning')
    conn.commit()
    return {'sample_number':seq,'status':status,'decision':decision,'transition':transition,'active':engine.active}


def demo_sequence(rows):
    """Repeat documented classroom stimuli; injected values never labeled as original."""
    src=rows[:9]
    tests=[
       {'temperature_c':'30.5','temperature_status':'OK','origin':'TEST_INJECTED'},
       {'temperature_c':'30.8','temperature_status':'OK','origin':'TEST_INJECTED'},
       {'temperature_c':'31.2','temperature_status':'OK','origin':'TEST_INJECTED'},
       *[{'temperature_c':'31.0','temperature_status':'OK','origin':'TEST_INJECTED'} for _ in range(16)],
       *[{'temperature_c':'','temperature_status':'MISSING','origin':'TEST_INJECTED'} for _ in range(4)],
       *[{'temperature_c':'28.4','temperature_status':'OK','origin':'TEST_INJECTED'} for _ in range(6)],
       *[{'temperature_c':'28.3','temperature_status':'OK','origin':'TEST_INJECTED'} for _ in range(6)],
    ]
    for x in tests:x.update({'timestamp':None,'sample_number':None})
    return src+tests+rows[9:19]


def run_worker(stop_event:threading.Event, *, db_path=None, csv_path=CSV_PATH,
               interval=2.0, demo=False, logger=None):
    log=logger or get_logger()
    conn=initialize(db_path or (ROOT/'state'/'monitor.db'))
    rows=source_rows(csv_path)
    if not rows:raise ValueError('Replay CSV is empty')
    sequence=demo_sequence(rows) if demo else rows
    # Cursor only commits after a row has been recorded; resume after restart.
    cursor=int(meta_get(conn,'cursor',0))
    log_event(log,'WORKER_STARTED',f'cursor={cursor}, replay_seconds={interval}, demo={demo}')
    insert_event(conn,'WORKER_STARTED',f'cursor={cursor} demo={demo}')
    try:
        while not stop_event.is_set():
            if PAUSE_FILE.exists():
                stop_event.wait(min(interval,0.2))
                continue
            index=cursor % len(sequence)
            row=sequence[index]
            process_one(conn,row,logger=log)
            cursor+=1
            meta_set(conn,'cursor',cursor)
            conn.commit()
            stop_event.wait(interval)
    except Exception as exc:
        log_event(log,'APPLICATION_ERROR',repr(exc),'error')
        insert_event(conn,'APPLICATION_ERROR',repr(exc))
        raise
    finally:
        log_event(log,'WORKER_STOPPED',f'cursor={cursor}')
        conn.close()
