from concurrent.futures import ThreadPoolExecutor
import json
import re
import sqlite3

import pytest

from classroom.core.db import MIGRATIONS
from classroom.core.errors import AppError
from classroom.web.app import create_app


def test_same_ip_blocks_browser_switch_no_time_expiry_and_new_registration_resets(services, active):
    classes, service = services
    cls, current = active
    ip = '192.168.1.22'
    service.submit(current['id'], 1, '甲', 'chrome', 'a', ip)
    # More than ten minutes elapsed must not unlock a second seat.
    with service.database.connect(write=True) as db:
        db.execute("UPDATE registrations SET updated_at='2000-01-01T00:00:00Z'")
    with pytest.raises(AppError, match='这台电脑'):
        service.submit(current['id'], 2, '乙', 'firefox', 'b', ip)
    assert service.active('another-browser', ip)['my_seat'] == 1
    new = service.open_round(cls['id'], current['id'])
    service.submit(new['round']['id'], 2, '甲', 'firefox', 'c', ip)
    service.close_round(new['round']['id'])
    other = classes.create('另一个班')
    next_class = service.open_round(other['id'])
    service.submit(next_class['round']['id'], 3, '甲', 'chrome', 'd', ip)
    assert service.get_arrangement(other['id'])['count'] == 1


def test_concurrent_same_ip_only_one_wins(services, active):
    service = services[1]
    def attempt(n):
        try:
            service.submit(active[1]['id'], n, '学生' + str(n), str(n), str(n), '10.0.0.9')
            return 'accepted'
        except AppError as error:
            return error.code
    with ThreadPoolExecutor(max_workers=16) as executor:
        results = list(executor.map(attempt, range(1, 17)))
    assert results.count('accepted') == 1 and results.count('device_registered') == 15


def test_clear_releases_ip_without_resurrecting_old_request(services, active):
    s = services[1]; rid = active[1]['id']
    s.submit(rid, 1, '甲', 'a', 'a', '10.0.0.1')
    s.correct(rid, 1, '')
    s.submit(rid, 2, '甲', 'b', 'b', '10.0.0.1')
    assert s.submit(rid, 1, '甲', 'a', 'a', '10.0.0.1')['duplicate']
    assert [r['seat_no'] for r in s.get_arrangement(active[0]['id'])['registrations']] == [2]


def test_ip_switch_can_be_disabled_for_shared_proxy(services, active):
    s = services[1]; s.limit_ip = False
    for n in (1, 2):
        s.submit(active[1]['id'], n, str(n), str(n), str(n), '10.0.0.1')
    assert s.get_arrangement(active[0]['id'])['count'] == 2


@pytest.mark.parametrize('name', ['张伟', '张 伟', ' 张伟 '])
def test_normalized_name_rejected_but_teacher_can_create_distinct_person(services, active, name):
    s = services[1]; rid = active[1]['id']
    s.submit(rid, 1, '张伟', 'a', 'a', '10.0.0.1')
    with pytest.raises(AppError, match='同名'):
        s.submit(rid, 2, name, 'b', 'b', '10.0.0.2')
    s.correct(rid, 2, '张伟', '另一位学生', force_new=True)
    entries = s.get_arrangement(active[0]['id'])['registrations']
    assert len(entries) == 2 and entries[0]['student_id'] != entries[1]['student_id']
    assert entries[0]['student_note'] == '' and entries[1]['student_note'] == '另一位学生'


def test_name_race(services, active):
    s = services[1]
    def attempt(n):
        try:
            s.submit(active[1]['id'], n, '张伟', str(n), str(n), '10.0.0.' + str(n))
            return 'accepted'
        except AppError as error:
            return error.code
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(attempt, range(1, 9)))
    assert results.count('accepted') == 1 and results.count('duplicate_name') == 7


def test_seat_config_global_notes_follow_students_archive_snapshot(services, active):
    classes, s = services; cls, current = active; lid = s.layouts.current['id']
    s.seats.update(lid, 3, True, '键盘损坏')
    with pytest.raises(AppError, match='停用'):
        s.submit(current['id'], 3, '甲', 'a', 'a', '10.0.0.1')
    s.correct(current['id'], 1, '甲', '长期请假')
    sid = s.get_arrangement(cls['id'])['registrations'][0]['student_id']
    # Occupied device can be marked disabled without deleting its person.
    s.seats.update(lid, 1, True, '显示器闪烁')
    assert s.get_arrangement(cls['id'])['count'] == 1
    new = s.open_round(cls['id'], current['id'])
    assert s.get_arrangement(cls['id'], current['id'])['round']['archived_at']
    s.submit(new['round']['id'], 2, '甲', 'b', 'b', '10.0.0.2')
    record = s.get_arrangement(cls['id'])['registrations'][0]
    assert record['student_id'] == sid and record['student_note'] == '长期请假'
    s.students.update_note(sid, '已返校')
    assert s.get_arrangement(cls['id'], current['id'])['registrations'][0]['student_note'] == '长期请假'
    assert s.get_arrangement(cls['id'])['registrations'][0]['student_note'] == '已返校'
    s.close_round(new['round']['id'])
    other = classes.create('另一班'); s.open_round(other['id'])
    assert next(c for c in s.get_arrangement(other['id'])['seat_configs'] if c['seat_no'] == 3)['note'] == '键盘损坏'
    assert s.students.list(other['id']) == []


def test_archives_current_context_and_restart(app, services, active):
    classes, s = services; cls, current = active
    s.correct(current['id'], 1, '甲')
    s.close_round(current['id'])
    other = classes.create('另一班'); other_round = s.open_round(other['id'])
    s.close_round(other_round['round']['id'])
    s.publish_class(cls['id'])
    assert s.active('a')['class']['id'] == cls['id']
    assert s.get_current_arrangement()['count'] == 1
    # Browsing another class does not publish it.
    s.get_arrangement(other['id'])
    assert s.active('a')['class']['id'] == cls['id']
    new_app = create_app(app.config['DATA_DIR'])
    assert new_app.extensions['seating'].active('a')['count'] == 1
    new = s.open_round(cls['id'], current['id'])
    assert new['count'] == 0
    with pytest.raises(AppError, match='已变更'):
        s.open_round(cls['id'], current['id'])
    assert len(s.rounds(cls['id'])) == 2


def test_notes_are_teacher_only_and_forwarded_ip_is_ignored(app, active):
    s = app.extensions['seating']; rid = active[1]['id']
    s.seats.update(s.layouts.current['id'], 2, True, 'PRIVATE-DEVICE')
    s.correct(rid, 3, '有备注学生', 'PRIVATE-STUDENT')
    def client():
        c = app.test_client(); page = c.get('/')
        csrf = re.search('name="csrf-token" content="([^"]+)"', page.text).group(1)
        return c, {'Origin': 'http://localhost', 'X-CSRF-Token': csrf}
    a, ha = client(); b, hb = client()
    a.post('/api/v1/student/registrations', json=dict(round_id=rid, seat_no=1, name='甲', request_id='a'), headers=ha,
           environ_overrides={'REMOTE_ADDR': '10.0.0.4'})
    result = b.post('/api/v1/student/registrations', json=dict(round_id=rid, seat_no=4, name='乙', request_id='b'),
                    headers={**hb, 'X-Forwarded-For': '10.0.0.5'}, environ_overrides={'REMOTE_ADDR': '10.0.0.4'})
    assert result.status_code == 409 and result.json['error']['code'] == 'device_registered'
    state = b.get('/api/v1/student/state').text
    assert 'PRIVATE-' not in state and 'source_ip' not in state and 'student_note' not in state
    assert b.put('/api/v1/teacher/layouts/classroom-64-v1/seats/2/config', json={'disabled': False, 'note': ''}, headers=hb).status_code == 403


def test_upgrade_real_v1_shape_preserves_duplicate_names_and_archives(tmp_path):
    root = tmp_path / 'data'; root.mkdir(); path = root / 'classroom.sqlite3'
    with sqlite3.connect(path) as db:
        db.executescript(MIGRATIONS[0][1])
        db.execute("INSERT INTO classes VALUES ('class','班级','2026-09-01')")
        layout = json.loads(open('resources/layout.json', encoding='utf-8').read())
        db.execute('INSERT INTO layouts VALUES (?, ?)', (layout['id'], json.dumps(layout, ensure_ascii=False, sort_keys=True)))
        for i in (1, 2):
            db.execute('INSERT INTO rounds VALUES (?, ?, ?, ?, ?, ?, ?)', (str(i) * 32, 'class', layout['id'], i, '2026-09-01', '2026-09-01' if i == 1 else None, i == 2))
        for i, rid in ((1, '1' * 32), (2, '2' * 32), (3, '2' * 32)):
            db.execute('INSERT INTO registrations VALUES (?, ?, ?, ?, ?, ?)', (str(i) * 32, rid, i, '张伟', str(i), '2026-09-01'))
        db.execute('PRAGMA user_version=1')
    app = create_app(root)
    with app.extensions['database'].connect() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 8
        assert db.execute('SELECT count(*) FROM registrations').fetchone()[0] == 3
        assert db.execute('SELECT count(DISTINCT student_id) FROM registrations WHERE round_id=?', ('2' * 32,)).fetchone()[0] == 2
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
    assert len(list((root / 'backups').glob('*.sqlite3'))) == 1
    s = app.extensions['seating']
    assert s.active('x')['count'] == 2
    assert not s.get_arrangement('class', '1' * 32)['is_current']
