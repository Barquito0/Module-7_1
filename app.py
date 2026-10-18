"""Flask monitoring dashboard. Use supervisor.py for unattended operation."""
from __future__ import annotations
import atexit
import os
import threading
import json
import traceback
from pathlib import Path
from flask import Flask, render_template, jsonify, request
from src.storage import ROOT, RUNTIME_DB, initialize, connect, history, insert_event, meta_get
from src.eventlog import get_logger, log_event
from src.health import health_snapshot
from src.monitor import run_worker
from src.watchdog import run_watchdog

DB_PATH=Path(os.getenv('MONITOR_DB', str(RUNTIME_DB)))
INTERVAL=float(os.getenv('REPLAY_SECONDS','2'))
DEGRADED_AFTER=float(os.getenv('STALE_DEGRADED_SECONDS','8'))
FAILED_AFTER=float(os.getenv('STALE_FAILED_SECONDS','18'))
DEMO=os.getenv('CLASSROOM_DEMO','0')=='1'
LOG_PATH=Path(os.getenv('MONITOR_LOG',str(ROOT/'logs'/'monitor.jsonl')))
logger=get_logger(LOG_PATH)
app=Flask(__name__)
stop_event=threading.Event()
worker=None
watchdog_thread=None


def launch():
    global worker,watchdog_thread
    with initialize(DB_PATH) as conn:
        prior = meta_get(conn, 'startup_seen', False)
        insert_event(conn,'STARTUP','restarting after prior session' if prior else 'first application startup')
        conn.execute("INSERT INTO monitor_meta(key,value) VALUES('startup_seen','true') ON CONFLICT(key) DO UPDATE SET value='true'")
        conn.commit()
    log_event(logger,'STARTUP',f'Application pid={os.getpid()}, previous_session={prior}')
    if prior:
        log_event(logger,'RECOVERING','Existing SQLite history reopened without resetting it')
        with connect(DB_PATH) as conn:
            insert_event(conn,'RECOVERING','Existing database reopened after process restart')
    worker=threading.Thread(target=run_worker,args=(stop_event,),kwargs={
        'db_path':DB_PATH,'interval':INTERVAL,'demo':DEMO,'logger':logger},daemon=True)
    worker.start()
    watchdog_thread=threading.Thread(target=run_watchdog,args=(stop_event,),kwargs={
        "db_path":DB_PATH,"degraded_after":DEGRADED_AFTER,
        "failed_after":FAILED_AFTER,"logger":logger},daemon=True)
    watchdog_thread.start()


def get_payload():
    with connect(DB_PATH) as conn:
        return health_snapshot(conn,degraded_after=DEGRADED_AFTER,failed_after=FAILED_AFTER)


@app.get('/')
def dashboard():
    snapshot=get_payload()
    return render_template('dashboard.html',snapshot=snapshot,
                           replay_seconds=INTERVAL, demo=DEMO)


@app.get('/api/status')
def api_status():
    return jsonify(get_payload())


@app.get('/api/history')
def api_history():
    limit=max(10,min(5000,int(request.args.get('limit','100'))))
    mode=request.args.get('mode','replay')
    if mode not in ('replay','archive'):
        return jsonify({'error':'invalid history mode'}),400
    with connect(DB_PATH) as conn:
        rows=[dict(r) for r in history(conn,limit=limit,
            live_only=(mode=='replay'),archive_only=(mode=='archive'))]
    return jsonify({'rows':rows,'mode':mode})


@app.get('/api/events')
def api_events():
    with connect(DB_PATH) as conn:
        ev=conn.execute('SELECT * FROM monitor_events ORDER BY id DESC LIMIT 40').fetchall()
    return jsonify([dict(x) for x in ev])


@app.get('/healthz')
def healthz():
    s=get_payload()
    return jsonify({'state':s['health'],'latest':s['latest_timestamp'],'reason':s['reason']}), (503 if s['health']=='FAILED' else 200)


@app.errorhandler(Exception)
def log_error(error):
    log_event(logger,'APPLICATION_ERROR',repr(error),'error')
    try:
        with connect(DB_PATH) as conn:insert_event(conn,'APPLICATION_ERROR',repr(error))
    except Exception:pass
    # Flask exceptions retain their HTTP status while still being logged.
    return jsonify({'error':'Application request failed','type':type(error).__name__}),getattr(error,'code',500)


if __name__=='__main__':
    launch()
    # Flask development server for local classroom demonstration only.
    # Production: use a process manager and proper WSGI worker configuration.
    app.run(host=os.getenv('HOST','127.0.0.1'),port=int(os.getenv('PORT','5000')),
            debug=False,use_reloader=False,threaded=True)
