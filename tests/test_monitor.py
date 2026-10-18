"""Pure-function and SQLite checks, including error and recovery scenarios."""
from datetime import datetime, timedelta, timezone
import sqlite3

from src.alerting import AlertEngine
from src.monitor import evaluate, process_one
from src.storage import initialize, connect, meta_get, latest_replay, total_counts, history
from src.health import health_snapshot
from src.watchdog import transition_event, poll_health


def test_alert_requires_three_valid_high_samples():
    e=AlertEngine()
    assert e.update(31.0) == 'NONE'
    assert e.update(30.4) == 'NONE'
    assert e.update(30.8) == 'ACTIVATED'
    assert e.active


def test_alert_reject_noise_resets_persistence():
    e=AlertEngine()
    assert e.update(31.0) == 'NONE'
    assert e.update(None,accepted=False) == 'NONE'
    assert e.update(31.0) == 'NONE'
    assert not e.active


def test_alert_hysteresis_and_two_sample_clear():
    e=AlertEngine()
    for v in (31,31,31): e.update(v)
    assert e.active
    assert e.update(29.0) == 'NONE'
    assert e.update(28.4) == 'NONE'
    assert e.update(28.3) == 'CLEARED'
    assert not e.active


def test_validation_keeps_raw_failed_readings_separate():
    raw,status,decision,reason=evaluate('60.3','OK')
    assert raw==60.3 and status=='OUT_OF_RANGE' and decision=='REJECTED'
    raw,status,decision,reason=evaluate('','MISSING')
    assert raw is None and status=='MISSING' and decision=='REJECTED'


def test_sqlite_archive_retained_and_new_replay_distinguished(tmp_path):
    db=tmp_path/'monitor.db'
    with initialize(db) as conn:
        before=total_counts(conn)
        assert before['historical']==8780//5
        assert before['replayed']==0
        result=process_one(conn,{'sample_number':1,'timestamp':'2026-10-01T08:00:00',
                        'temperature_c':'22.5','temperature_status':'OK'})
        assert result['decision']=='ACCEPTED'
        new=latest_replay(conn)
        assert new['accepted_value']==22.5
        assert new['source_timestamp']=='2026-10-01T08:00:00'
        assert new['timestamp_source']=='CLASSROOM_REPLAY_UTC'
        assert new['origin']=='MODULE6_SOURCE_REPLAY'
        after=total_counts(conn)
        assert after['historical']==before['historical']
        assert after['replayed']==1
    with connect(db) as conn:
        assert total_counts(conn)['replayed']==1
        assert len(history(conn,archive_only=True,limit=10))==10
        assert len(history(conn,live_only=True,limit=10))==1


def test_rejected_or_missing_not_silently_filled(tmp_path):
    with initialize(tmp_path/'history.db') as conn:
        result=process_one(conn,{'temperature_c':'','temperature_status':'MISSING',
                                'origin':'TEST_INJECTED'})
        assert result['decision']=='REJECTED'
        latest=latest_replay(conn)
        assert latest['raw_value'] is None
        assert latest['accepted_value'] is None
        assert latest['status']=='MISSING'
        snap=health_snapshot(conn,now=datetime.fromisoformat(latest['captured_at_utc']))
        assert snap['health']=='DEGRADED'
        assert snap['current_value'] is None


def test_stale_failed_and_recovered_health(tmp_path):
    with initialize(tmp_path/'db.db') as conn:
        t=datetime.now(timezone.utc)
        process_one(conn,{'temperature_c':'22.0','temperature_status':'OK'},at=t.isoformat())
        assert health_snapshot(conn,now=t+timedelta(seconds=1))['health']=='HEALTHY'
        mid=health_snapshot(conn,now=t+timedelta(seconds=9))
        assert mid['health']=='DEGRADED' and mid['current_value'] is None
        assert health_snapshot(conn,now=t+timedelta(seconds=19))['health']=='FAILED'
        second=t+timedelta(seconds=20)
        process_one(conn,{'temperature_c':'22.1','temperature_status':'OK'},at=second.isoformat())
        assert health_snapshot(conn,now=second+timedelta(seconds=1))['health']=='HEALTHY'


def test_watchdog_logs_transitions_without_spam(tmp_path):
    with initialize(tmp_path/'db.db') as conn:
        t=datetime.now(timezone.utc)
        process_one(conn,{'temperature_c':'22.0','temperature_status':'OK'},at=t.isoformat())
        state=poll_health(conn,None,now=t+timedelta(seconds=1))
        assert state=='HEALTHY'
        state=poll_health(conn,state,now=t+timedelta(seconds=9))
        assert state=='DEGRADED'
        assert poll_health(conn,state,now=t+timedelta(seconds=10))=='DEGRADED'
        state=poll_health(conn,state,now=t+timedelta(seconds=19))
        assert state=='FAILED'
        process_one(conn,{'temperature_c':'22.1','temperature_status':'OK'},
                    at=(t+timedelta(seconds=20)).isoformat())
        assert poll_health(conn,state,now=t+timedelta(seconds=20.5))=='HEALTHY'
        events=[r[0] for r in conn.execute('SELECT event FROM monitor_events').fetchall()]
        assert events.count('STALE_INPUT')==1
        assert events.count('INPUT_FAILED')==1
        assert events.count('HEALTH_RECOVERED')==1


def test_replay_cursor_survives_sqlite_restart(tmp_path):
    from src.storage import meta_set
    db=tmp_path/'database.db'
    with initialize(db) as c:
        meta_set(c,'cursor',14);c.commit()
    with initialize(db) as c:
        assert meta_get(c,'cursor')==14


def test_original_module6_archive_contains_two_known_gaps(tmp_path):
    from datetime import datetime
    db=tmp_path/'monitor.db'
    with initialize(db) as c:
        rows=c.execute("SELECT timestamp FROM readings WHERE sensor='temperature' AND captured_at_utc IS NULL ORDER BY timestamp").fetchall()
        separations=[(datetime.fromisoformat(b[0])-datetime.fromisoformat(a[0])).total_seconds()
                     for a,b in zip(rows,rows[1:])]
        assert sorted([round(t/60) for t in separations if t>90])==[21,26]


def test_transition_event_types():
    assert transition_event('HEALTHY','DEGRADED','Replay input stale')=='STALE_INPUT'
    assert transition_event('DEGRADED','FAILED','No replay input')=='INPUT_FAILED'
    assert transition_event('FAILED','HEALTHY','OK')=='HEALTH_RECOVERED'
    assert transition_event('HEALTHY','HEALTHY','OK') is None
