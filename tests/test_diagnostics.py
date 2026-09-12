import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from test_api import login
from classroom.core.diagnostics import WaitressDiagnosticHandler


def test_health_does_not_need_database(app, monkeypatch):
    def unavailable(*args, **kwargs):
        raise AssertionError('health must not query database')
    monkeypatch.setattr(app.extensions['database'], 'connect', unavailable)
    assert app.extensions['rollcall'].student_announcement('10.0.0.1','client')['announcement'] is None
    response = app.test_client().get('/health')
    assert response.status_code == 200
    assert len(response.headers['X-Request-ID']) == 12


def test_diagnostic_privacy_and_database_lock(app):
    database = app.extensions['database']
    diag = app.extensions['diagnostics']
    ready = threading.Event()
    def writer():
        ready.set()
        with database.connect(write=True):
            pass
    with ThreadPoolExecutor(1) as pool:
        with database.connect(write=True):
            future = pool.submit(writer)
            ready.wait(2)
            time.sleep(.25)
        future.result(timeout=3)
    handler = WaitressDiagnosticHandler(diag)
    handler.emit(logging.LogRecord('waitress', logging.ERROR, '', 0, 'private name SECRET request body', (), None))
    app.test_client().get('/missing?name=SECRET')
    lines = (diag.root / 'diagnostics.jsonl').read_text(encoding='utf-8')
    assert 'SECRET' not in lines and 'private name' not in lines
    events = [json.loads(line) for line in lines.splitlines()]
    assert any(e['event'] == 'database' and e['begin_wait_ms'] >= 100 for e in events)
    assert not diag.active


def test_class_rename_counts_and_permissions(app, active):
    client, headers = login(app)
    cid, rid = active[0]['id'], active[1]['id']
    client.put('/api/v1/teacher/rounds/'+rid+'/seats/1', json={'name':'虚构学生'}, headers=headers)
    classes = client.get('/api/v1/teacher/classes').json['classes']
    assert next(c for c in classes if c['id']==cid)['student_count'] == 1
    path = '/api/v1/teacher/classes/'+cid
    assert app.test_client().put(path,json={'name':'越权','graduation_year':2029}).status_code == 403
    assert client.put(path,json={'name':'新班名','graduation_year':2029},headers=headers).status_code == 200
    assert client.put(path,json={'name':'新班名','graduation_year':True},headers=headers).status_code == 400
    cls = next(c for c in client.get('/api/v1/teacher/classes').json['classes'] if c['id']==cid)
    assert cls['name']=='新班名' and cls['graduation_year']==2029
