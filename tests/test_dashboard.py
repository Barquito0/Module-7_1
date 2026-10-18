"""HTTP assertions are run in CI with Flask installed."""
import pytest

flask=pytest.importorskip('flask')
from src.storage import initialize
import app as dashboard_app


def test_flask_dashboard_and_history_endpoints(tmp_path,monkeypatch):
    db=tmp_path/'monitor.db'
    with initialize(db):pass
    monkeypatch.setattr(dashboard_app,'DB_PATH',db)
    client=dashboard_app.app.test_client()
    page=client.get('/')
    assert page.status_code==200
    assert b'Temperature monitoring' in page.data
    latest=client.get('/api/status')
    assert latest.status_code==200
    assert latest.json['health']=='RECOVERING'
    archive=client.get('/api/history?mode=archive&limit=5000')
    assert archive.status_code==200
    assert len(archive.json['rows'])==1756
    assert client.get('/api/history?mode=nope').status_code==400
    assert client.get('/healthz').status_code==200
