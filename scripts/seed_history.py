"""Recreate the original Module 6 SQLite source database from CSV.

No synthetic observations or reconstructed timestamps are introduced.
The source database is rebuilt ONLY on explicit invocation, never on restart.
"""
from __future__ import annotations
import csv
from pathlib import Path
from src.storage import ROOT, SEED_DB

FIELDS=[('temperature','temperature_c','temperature_status','C',0,50),
('humidity','humidity_percent','humidity_status','%',0,100),
('light','light_raw','light_status','raw',None,None),
('distance','distance_cm','distance_status','cm',None,None),
('potentiometer','potentiometer_percent','potentiometer_status','%',0,100)]


def main():
    import sqlite3
    source=ROOT/'data'/'module6_sample_sensor_history.csv'
    if SEED_DB.exists():
        raise SystemExit('Seed already exists; refusing to overwrite Module 6 evidence')
    SEED_DB.parent.mkdir(exist_ok=True)
    with sqlite3.connect(SEED_DB) as conn:
        conn.execute('''CREATE TABLE readings (sensor TEXT NOT NULL,
            sample_number INTEGER NOT NULL, timestamp TEXT NOT NULL,
            raw_value REAL, accepted_value REAL, unit TEXT NOT NULL,
            status TEXT NOT NULL, decision TEXT NOT NULL, reason TEXT NOT NULL,
            timestamp_source TEXT NOT NULL, PRIMARY KEY(sensor,sample_number))''')
        conn.execute('CREATE INDEX idx_readings_sensor_time ON readings(sensor,timestamp)')
        with source.open(newline='',encoding='utf-8') as f:
            for row in csv.DictReader(f):
                for sensor,field,status_field,unit,lo,hi in FIELDS:
                    raw=float(row[field]) if row[field].strip() else None
                    status=row[status_field]
                    valid=raw is not None and status=='OK' and (lo is None or raw>=lo) and (hi is None or raw<=hi)
                    conn.execute('''INSERT INTO readings VALUES(?,?,?,?,?,?,?,?,?,?)''',(
                        sensor,int(row['sample_number']),row['timestamp'],raw,raw if valid else None,
                        unit,status,'ACCEPTED' if valid else 'REJECTED',
                        'source status OK and numeric value available' if valid else 'nonaccepted original source reading',
                        'ORIGINAL_CSV'))
    print('Reconstructed original Module 6 database:',SEED_DB)

if __name__=='__main__':main()
