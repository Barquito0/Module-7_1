"""Unattended process supervisor. Restarts Flask app after SIGKILL/crashes."""
from __future__ import annotations
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from src.eventlog import get_logger, log_event
from src.storage import ROOT, initialize, insert_event

SLEEP=float(os.getenv('RESTART_DELAY_SECONDS','1'))
MIN_UPTIME=float(os.getenv('CRASH_LOOP_UPTIME','1.0'))
logger=get_logger(name='monitor7.supervisor')
stop=False
child=None

def shutdown(signum,frame):
    global stop
    stop=True
    if child is not None and child.poll() is None:
        child.terminate()

signal.signal(signal.SIGTERM,shutdown)
signal.signal(signal.SIGINT,shutdown)


def main():
    global child
    restart_count=0
    with initialize() as conn:
        insert_event(conn,'SUPERVISOR_STARTED','Process supervisor operational')
    log_event(logger,'SUPERVISOR_STARTED','Unattended supervisor operational')
    while not stop:
        start=time.monotonic()
        env={**os.environ,'PYTHONUNBUFFERED':'1'}
        child=subprocess.Popen([sys.executable,'-u',str(ROOT/'app.py')],cwd=ROOT,env=env)
        log_event(logger,'PROCESS_LAUNCHED',f'child_pid={child.pid}; restart_count={restart_count}')
        exit_code=child.wait()
        uptime=time.monotonic()-start
        log_event(logger,'PROCESS_EXITED',f'child_pid={child.pid}; code={exit_code}; uptime={uptime:.2f}s', 'warning')
        with initialize() as conn:
            insert_event(conn,'PROCESS_EXITED',f'pid={child.pid}, code={exit_code}, uptime={uptime:.2f}s')
        if stop:break
        restart_count+=1
        with initialize() as conn:
            insert_event(conn,'RESTART_SCHEDULED',f'after child={child.pid}, restart_count={restart_count}')
        log_event(logger,'RESTART_SCHEDULED',f'after child={child.pid}, restart_count={restart_count}')
        # Guard against an unbounded rapid crash loop.
        time.sleep(max(SLEEP,3.0) if uptime<MIN_UPTIME else SLEEP)
    log_event(logger,'SUPERVISOR_STOPPED','Supervisor shutting down cleanly')

if __name__=='__main__':main()
