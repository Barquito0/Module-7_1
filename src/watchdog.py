"""Independent watchdog records stale/failed input and recovery transitions."""
from __future__ import annotations
from threading import Event
from .storage import connect, insert_event
from .health import health_snapshot
from .eventlog import get_logger, log_event


def transition_event(previous, current, reason):
    """Return a single named transition event, not one event per poll."""
    if current == previous:
        return None
    if current == 'FAILED':
        return 'INPUT_FAILED'
    if current == 'DEGRADED' and 'stale' in reason.lower():
        return 'STALE_INPUT'
    if current == 'HEALTHY' and previous in ('DEGRADED', 'FAILED', 'RECOVERING'):
        return 'HEALTH_RECOVERED'
    return 'HEALTH_CHANGED'


def poll_health(conn, previous, *, degraded_after=8, failed_after=18, now=None, logger=None):
    snap = health_snapshot(conn, now=now, degraded_after=degraded_after,
                           failed_after=failed_after)
    current = snap['health']
    event = transition_event(previous, current, snap['reason'])
    if event:
        message = f'{previous or "STARTING"} -> {current}; {snap["reason"]}'
        insert_event(conn, event, message)
        if logger:
            log_event(logger, event, message,
                      'warning' if current in ('DEGRADED','FAILED') else 'info')
    return current


def run_watchdog(stop_event: Event, *, db_path, degraded_after, failed_after,
                 logger=None, period=0.35):
    logger = logger or get_logger()
    previous = None
    while not stop_event.wait(period):
        try:
            with connect(db_path) as conn:
                previous = poll_health(conn, previous,
                    degraded_after=degraded_after, failed_after=failed_after,
                    logger=logger)
        except Exception as exc:
            log_event(logger, 'APPLICATION_ERROR',
                      f'watchdog failed: {exc!r}', 'error')
