import re


def login(app):
    client = app.test_client()
    response = client.get('/teacher?key=test-bootstrap', follow_redirects=True)
    csrf = re.search(r'name="csrf-token" content="([^"]+)"', response.text).group(1)
    return client, {"Origin": "http://localhost", "X-CSRF-Token": csrf}


def test_teacher_access_boundaries(app, active):
    client, headers = login(app)
    assert client.get('/api/v1/teacher/classes').status_code == 200
    for path in ('/teacher?key=test-bootstrap', '/api/v1/teacher/classes',
                 '/api/v1/teacher/classes/' + active[0]['id'] + '/export'):
        assert client.get(path, environ_overrides={'REMOTE_ADDR': '192.168.1.20'}).status_code == 403
        assert client.get(path, base_url='http://attacker.example').status_code == 403
    student = app.test_client()
    assert student.get('/api/v1/teacher/classes').status_code == 403
    assert client.post('/api/v1/teacher/classes', json={'name': '班级'}).status_code == 403
    assert client.post('/api/v1/teacher/classes', json={'name': '班级'}, headers={**headers, 'Origin': 'http://evil.example'}).status_code == 403
    assert client.post('/api/v1/teacher/classes', json={'name': '班级'}, headers={**headers, 'X-CSRF-Token': 'wrong'}).status_code == 403
    assert client.post('/api/v1/teacher/classes', json={'name': '班级'}, headers=headers).status_code == 201


def test_student_flow_and_bad_payloads(app, active):
    client = app.test_client()
    page = client.get('/')
    token = re.search(r'name="csrf-token" content="([^"]+)"', page.text).group(1)
    headers = {'Origin': 'http://localhost', 'X-CSRF-Token': token}
    current = client.get('/api/v1/student/state').json
    assert current['round']['id'] == active[1]['id']
    payload = dict(round_id=active[1]['id'], seat_no=1, name='学生', request_id='abc')
    response = client.post('/api/v1/student/registrations', json=payload, headers=headers)
    assert response.status_code == 200 and response.json['accepted']
    assert client.get('/api/v1/student/state').json['my_seat'] == 1
    assert client.put('/api/v1/teacher/rounds/' + active[1]['id'] + '/seats/1', json={'name': '乱改'}, headers=headers).status_code == 403
    assert client.post('/api/v1/student/registrations', json=[], headers=headers).status_code == 400
    assert client.post('/api/v1/student/registrations', json={**payload, 'round_id': {}}, headers=headers).status_code == 400
    assert client.post('/api/v1/student/registrations', json={**payload, 'name': 'a' * 20000}, headers=headers).status_code == 413
    assert "frame-ancestors 'none'" in page.headers['Content-Security-Policy']


def test_full_teacher_http_flow(app):
    client, headers = login(app)
    cls = client.post('/api/v1/teacher/classes', json={'name': '高一'}, headers=headers).json
    assert client.post('/api/v1/teacher/classes', json={'name': '高一'}, headers=headers).status_code == 409
    current = client.post('/api/v1/teacher/classes/' + cls['id'] + '/rounds', json={}, headers=headers).json
    rid = current['round']['id']
    assert client.put('/api/v1/teacher/rounds/' + rid + '/seats/64', json={'name': '学生64'}, headers=headers).status_code == 200
    assert client.post('/api/v1/teacher/rounds/' + rid + '/close', json={}, headers=headers).status_code == 200
    assert client.get('/api/v1/teacher/classes/' + cls['id'] + '/rounds').json['rounds'][0]['is_open'] == 0
    exported = client.get('/api/v1/teacher/classes/' + cls['id'] + '/export')
    assert exported.status_code == 200 and exported.data[:2] == b'PK'
    assert 'attachment;' in exported.headers['Content-Disposition']
