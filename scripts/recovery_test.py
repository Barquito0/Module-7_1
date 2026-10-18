"""Real unattended-recovery exercise with HTTP, SQLite, logs and browser evidence.

Use on a machine with Flask, Chromium/Chrome, and the original source CSV.
Run via: python scripts/recovery_test.py
Does not fabricate dashboard screenshots; each PNG is captured from the live Flask URL.
"""
from __future__ import annotations
import csv
import json
import os
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen
from urllib.error import HTTPError

ROOT=Path(__file__).resolve().parents[1]
EVIDENCE=ROOT/'evidence'
STATE=ROOT/'state'
DB=STATE/'monitor.db'
PAUSE=STATE/'pause.flag'
PORT='5127'
BASE=f'http://127.0.0.1:{PORT}'
EVIDENCE.mkdir(exist_ok=True)


def request(path='/api/status'):
    with urlopen(BASE+path, timeout=2) as response:
        return json.loads(response.read().decode()) if path!='/' else response.read().decode()


def until(label,predicate,timeout=28):
    start=time.monotonic()
    last=None
    while time.monotonic()-start<timeout:
        try:
            snap=request()
            last=snap
            if predicate(snap):return snap
        except Exception as exc:last={'network_error':str(exc)}
        time.sleep(.12)
    raise AssertionError(f'{label}: timed out; last={last}')


def take_screenshot(name,url='/'):
    chrome=next((p for n in ('google-chrome','chromium','chromium-browser','chrome')
        if (p:=shutil.which(n))),None)
    if not chrome:
        raise RuntimeError('A real browser is required to capture screenshots; Chrome/Chromium was not found')
    output=EVIDENCE/name
    cmd=[chrome,'--headless=new','--no-sandbox','--disable-gpu',
         '--disable-dev-shm-usage','--hide-scrollbars','--window-size=1480,1180',
         '--virtual-time-budget=1400','--screenshot='+str(output),BASE+url]
    result=subprocess.run(cmd,capture_output=True,text=True,timeout=25)
    if result.returncode!=0 or not output.is_file() or output.stat().st_size<2000:
        raise RuntimeError(f'Browser screenshot failed ({name}): {result.stderr[-600:]}')
    return str(output.relative_to(ROOT))


def event_names():
    with sqlite3.connect(DB) as db:
        return [x[0] for x in db.execute('SELECT event FROM monitor_events ORDER BY id')]


def child_pid(parent):
    try:
        out=subprocess.check_output(['ps','-o','pid=','--ppid',str(parent)],text=True)
        ids=[int(x) for x in out.split()]
        return ids[0] if ids else None
    except Exception:
        return None


def write_json(name,payload):
    (EVIDENCE/name).write_text(json.dumps(payload,indent=2,default=str)+'\n',encoding='utf-8')


def main():
    if DB.exists():DB.unlink()  # Only reset the *test runtime* DB, never the source seed DB.
    for suffix in ('-wal','-shm'):
        p=Path(str(DB)+suffix)
        if p.exists():p.unlink()
    PAUSE.unlink(missing_ok=True)
    logfile=ROOT/'logs'/'monitor.jsonl'
    logfile.unlink(missing_ok=True)
    env={**os.environ,'CLASSROOM_DEMO':'1','REPLAY_SECONDS':'.35','PORT':PORT,
         'STALE_DEGRADED_SECONDS':'2.8','STALE_FAILED_SECONDS':'5.5',
         'RESTART_DELAY_SECONDS':'.5','PYTHONUNBUFFERED':'1'}
    supervisor=subprocess.Popen([sys.executable,'-u',str(ROOT/'supervisor.py')],
                                 cwd=ROOT,env=env,stdout=(EVIDENCE/'console.log').open('w'),
                                 stderr=subprocess.STDOUT,start_new_session=True)
    stages={}
    try:
        snap=until('first fresh sensor',lambda s:s.get('health')=='HEALTHY' and
                     s.get('counts',{}).get('replayed',0)>=2,timeout=20)
        stages['dashboard_running']=snap
        take_screenshot('dashboard_running.png')
        take_screenshot('historical_view.png','/?mode=archive')
        stages['historical_count']=len(request('/api/history?mode=archive&limit=5000')['rows'])
        assert stages['historical_count']==1756
        # Controlled API error exercises JSONL + SQLite application-error logging.
        try:
            request('/api/history?limit=not-a-number')
            raise AssertionError('Invalid API input should produce HTTP 500')
        except HTTPError as err:
            assert err.code==500

        snap=until('persistent high alert',lambda s:s.get('alert_active') is True,timeout=24)
        PAUSE.touch()
        stages['alert_active']=snap
        take_screenshot('alert_active.png')
        PAUSE.unlink(missing_ok=True)

        snap=until('missing condition',lambda s:s.get('sensor_status')=='MISSING',timeout=22)
        PAUSE.touch()
        stages['missing_input']=snap
        take_screenshot('missing_input.png')
        PAUSE.unlink(missing_ok=True)

        snap=until('alert cleared',lambda s:not s.get('alert_active') and
                  'ALERT_CLEARED' in event_names() and s.get('health')=='HEALTHY',timeout=24)
        PAUSE.touch()
        stages['alert_cleared']=snap
        take_screenshot('alert_cleared.png')

        snap=until('stale condition',lambda s:s.get('health')=='DEGRADED' and
                   'stale' in s.get('reason','').lower(),timeout=15)
        stages['stale_input']=snap
        take_screenshot('stale_input.png')
        snap=until('failed condition',lambda s:s.get('health')=='FAILED',timeout=12)
        stages['failed_input']=snap
        take_screenshot('failed_input.png')
        PAUSE.unlink(missing_ok=True)
        snap=until('recovery from data interruption',lambda s:s.get('health')=='HEALTHY',timeout=15)
        stages['data_recovered']=snap

        # True hard-kill of the *application* process; supervisor remains alive.
        before_pid=child_pid(supervisor.pid)
        if not before_pid:raise AssertionError('Flask child PID not found; cannot claim interruption test')
        rows_before=sqlite3.connect(DB).execute('SELECT COUNT(*) FROM readings').fetchone()[0]
        os.kill(before_pid,signal.SIGKILL)
        start=time.monotonic()
        after_pid=None
        while time.monotonic()-start<20:
            candidate=child_pid(supervisor.pid)
            if candidate and candidate!=before_pid:
                after_pid=candidate
                break
            time.sleep(.2)
        if not after_pid:raise AssertionError('Supervisor did not restart killed application process')
        snap=until('final healthy state',lambda s:s.get('health')=='HEALTHY',timeout=20)
        rows_after=sqlite3.connect(DB).execute('SELECT COUNT(*) FROM readings').fetchone()[0]
        if rows_after<rows_before:raise AssertionError('SQLite history shrank after process restart')
        stages['process_recovery']={'killed_pid':before_pid,'new_pid':after_pid,
                    'readings_before':rows_before,'readings_after':rows_after,
                    'final_snapshot':snap}
        take_screenshot('final_healthy.png')
        take_screenshot('recovery_logs.png')
        names=event_names()
        required=['STARTUP','READING_ACCEPTED','ALERT_ACTIVATED','ALERT_CLEARED',
                  'MISSING_INPUT','STALE_INPUT','INPUT_FAILED','HEALTH_RECOVERED',
                  'PROCESS_EXITED','RESTART_SCHEDULED','RECOVERING','APPLICATION_ERROR']
        absent=[x for x in required if x not in names]
        if absent:raise AssertionError('Required event logs missing: '+str(absent))
        stages['required_event_counts']={e:names.count(e) for e in required}
        stages['verified']=True
        write_json('recovery_test.json',stages)
        print(json.dumps({'result':'PASS','screenshots':9,'event_counts':stages['required_event_counts'],
            'before':rows_before,'after':rows_after},indent=2))
    except Exception as error:
        write_json('recovery_failure.json',{'error':repr(error),'stages':stages,'events':event_names() if DB.exists() else []})
        raise
    finally:
        PAUSE.unlink(missing_ok=True)
        supervisor.send_signal(signal.SIGTERM)
        try:supervisor.wait(timeout=7)
        except subprocess.TimeoutExpired:supervisor.kill();supervisor.wait()
        if logfile.exists():shutil.copy2(logfile,EVIDENCE/'application_logs.jsonl')
        if DB.exists():
            with sqlite3.connect(DB) as conn:
                with (EVIDENCE/'application_events.csv').open('w',newline='',encoding='utf-8') as f:
                    writer=csv.writer(f)
                    writer.writerow(['timestamp_utc','event','detail'])
                    writer.writerows(conn.execute('SELECT timestamp_utc,event,detail FROM monitor_events ORDER BY id'))


if __name__=='__main__':main()
