"""Line-delimited JSON audit log: process startup, sensor activity and recovery."""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from logging.handlers import RotatingFileHandler

ROOT = Path(__file__).resolve().parents[1]

class StructuredFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps({'timestamp_utc':datetime.now(timezone.utc).isoformat(timespec='milliseconds'),
                           'level': record.levelname,'event':getattr(record,'event','APPLICATION'),
                           'message':record.getMessage(), 'process_id':record.process})

def get_logger(path=None, name='monitor7'):
    path=Path(path or ROOT/'logs'/'monitor.jsonl')
    path.parent.mkdir(parents=True,exist_ok=True)
    log=logging.getLogger(name)
    log.setLevel(logging.INFO)
    log.propagate=False
    # One handler per process/logger. Worker and supervisor use separate named loggers.
    if not log.handlers:
        h=RotatingFileHandler(path,maxBytes=3_000_000,backupCount=3)
        h.setFormatter(StructuredFormatter())
        log.addHandler(h)
    return log

def log_event(logger, event, message, level='info'):
    getattr(logger,level)(message,extra={'event':event})
