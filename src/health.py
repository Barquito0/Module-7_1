"""Compute live health from REPLAY ARRIVAL time, not archived original timestamps."""
from datetime import datetime, timezone
from .storage import latest_replay, meta_get, total_counts


def now_utc():
    return datetime.now(timezone.utc)


def health_snapshot(conn, *, now=None, degraded_after=8.0, failed_after=18.0):
    now=now or now_utc()
    latest=latest_replay(conn)
    state=meta_get(conn,'alert_engine',{})
    alert=bool(state.get('active',False))
    counts=total_counts(conn)
    if latest is None:
        return {'health':'RECOVERING','reason':'Awaiting first replay sample',
                'age_seconds':None,'reading':None,'alert_active':alert,
                'counts':counts,'latest_timestamp':None,'current_value':None,
                'sensor_status':'NO_REPLAY_DATA','origin':None}
    captured=datetime.fromisoformat(latest['captured_at_utc'])
    age=max(0,(now-captured).total_seconds())
    valid=latest['decision']=='ACCEPTED'
    if age > failed_after:
        health,why='FAILED','No replay input received within failure limit'
    elif age > degraded_after:
        health,why='DEGRADED','Replay input stale; last reading is NOT current'
    elif not valid:
        health,why='DEGRADED','Latest received sensor value is missing/rejected'
    elif alert:
        health,why='DEGRADED','Persistent high-temperature alert active'
    else:
        health,why='HEALTHY','Accepted replay value is fresh; no active alert'
    current=(latest['accepted_value'] if valid and age<=degraded_after else None)
    return {'health':health,'reason':why,'age_seconds':round(age,2),
            'reading':{'raw':latest['raw_value'],'accepted':latest['accepted_value'],
                       'status':latest['status'],'source_timestamp':latest['source_timestamp'],
                       'origin':latest['origin'],'decision':latest['decision']},
            'alert_active':alert,'counts':counts,'latest_timestamp':latest['captured_at_utc'],
            'current_value':current,'sensor_status':latest['status'], 'origin':latest['origin']}
