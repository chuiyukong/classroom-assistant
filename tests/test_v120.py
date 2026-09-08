from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import re
import shutil
import sqlite3
from pathlib import Path
import pytest
from classroom.core.errors import AppError
from classroom.core.db import MIGRATIONS
from classroom.web.app import create_app


def lesson(app, active, n=3):
    seating = app.extensions['seating']
    for i in range(1, n + 1):
        seating.correct(active[1]['id'], i, '测试学生' + str(i))
    seating.close_round(active[1]['id'])
    service = app.extensions['attendance']
    d = service.start(active[1]['id'])
    return service, d['lesson']['id'], d['entries']


def test_snapshot_move_long_leave_and_next_lesson(app, active):
    s, lid, rows = lesson(app, active)
    s.action(lid, 'open')
    s.mark(lid, rows[0]['student_id'], 'long_leave')
    s.checkin(lid, rows[1]['student_id'], 64, '10.0.0.2', 'client2', move_reason='device_fault')
    assert s.detail(lid)['counts']['actual'] == 1
    assert app.extensions['seating'].get_current_arrangement()['registrations'][1]['seat_no'] == 2
    next_lesson = s.start(active[1]['id'])
    assert next_lesson['entries'][0]['status'] == 'long_leave'
    assert next_lesson['counts']['actual'] == 0
    assert s.detail(lid)['entries'][2]['status'] == 'absent'
    with pytest.raises(AppError):
        s.mark(lid, rows[0]['student_id'], 'pending')
    new_id = next_lesson['lesson']['id']; s.action(new_id, 'open')
    s.checkin(new_id, rows[0]['student_id'], 2, '10.0.0.1', 'client1', move_reason='device_fault')
    assert s.start(active[1]['id'])['entries'][0]['status'] == 'pending'
    assert s.detail(lid)['entries'][0]['status'] == 'long_leave'


def test_concurrent_64_and_duplicate_receipt(app, active):
    s, lid, rows = lesson(app, active, 64); s.action(lid, 'open')
    def submit(i):
        return s.checkin(lid, rows[i]['student_id'], i + 1, '10.0.0.' + str(i + 1), 'c' + str(i))
    with ThreadPoolExecutor(max_workers=64) as pool:
        assert all(r['accepted'] for r in pool.map(submit, range(64)))
    assert s.detail(lid)['counts']['actual'] == 64
    assert submit(0)['duplicate']
    with pytest.raises(AppError):
        s.checkin(lid, rows[0]['student_id'], 64, '10.0.0.1', 'c0')


def test_same_seat_race_and_ip_spoof_resistance(app, active):
    s, lid, rows = lesson(app, active); s.action(lid, 'open')
    def submit(i):
        try:
            s.checkin(lid, rows[i]['student_id'], 64, '10.0.0.' + str(i+1), 'c'+str(i), move_reason='device_fault'); return True
        except AppError:
            return False
    with ThreadPoolExecutor(max_workers=3) as pool:
        assert sum(pool.map(submit, range(3))) == 1
    winner = next(r for r in s.detail(lid)['entries'] if r['signed_at'])
    winner_index = next(i for i, r in enumerate(rows) if r['student_id'] == winner['student_id'])
    loser = next(r for r in rows if r['student_id'] != winner['student_id'])
    with pytest.raises(AppError, match='本机'):
        s.checkin(lid, loser['student_id'], 63, '10.0.0.'+str(winner_index+1), 'different-browser', move_reason='device_fault')


def test_late_close_teacher_and_rollcall_source(app, active):
    s, lid, rows = lesson(app, active); draw = app.extensions['rollcall']
    assert draw.draw(lid)['source'] == 'seating'
    s.action(lid, 'open')
    with pytest.raises(AppError):
        draw.draw(lid)
    with app.extensions['database'].connect(write=True) as db:
        db.execute('UPDATE lessons SET attendance_started_at=? WHERE id=?', ((datetime.now(timezone.utc)-timedelta(minutes=8)).isoformat(),lid))
    s.checkin(lid, rows[0]['student_id'], 64, '10.0.0.1','a', move_reason='device_fault')
    signed = s.detail(lid)['entries'][0]
    assert signed['status'] == 'late' and 175 < signed['late_seconds'] < 185
    assert draw.draw(lid)['student_id'] == rows[0]['student_id']
    s.action(lid, 'close')
    with pytest.raises(AppError):
        s.checkin(lid,rows[1]['student_id'],2,'10.0.0.2','b')
    s.checkin(lid,rows[1]['student_id'],2,teacher=True)
    assert s.detail(lid)['counts']['actual'] == 2
    s.action(lid,'end')
    with pytest.raises(AppError):
        draw.draw(lid)


def test_names_disabled_and_privacy(app, active):
    s, lid, rows = lesson(app, active); s.action(lid,'open')
    with pytest.raises(AppError):
        s.checkin(lid,'non-roster',4,'10.0.0.1','a')
    app.extensions['seat_configs'].update(app.extensions['layouts'].current['id'],64,True,'PRIVATE-DEVICE')
    with pytest.raises(AppError):
        s.checkin(lid,rows[0]['student_id'],64,'10.0.0.1','a')
    s.mark(lid,rows[0]['student_id'],'long_leave')
    text=json.dumps(s.state(True,'10.0.0.1','a'))
    assert 'long_leave' not in text and 'source_ip' not in text and 'PRIVATE' not in text
    assert 64 not in s.state(True,'10.0.0.1','a')['available_seats']


def test_same_name_requires_teacher(app, active):
    seating=app.extensions['seating']
    seating.correct(active[1]['id'],1,'同名')
    seating.correct(active[1]['id'],2,'同名',force_new=True)
    seating.close_round(active[1]['id'])
    s=app.extensions['attendance']; d=s.start(active[1]['id']); lid=d['lesson']['id'];s.action(lid,'open')
    with pytest.raises(AppError,match='同名'):
        s.checkin(lid,d['entries'][0]['student_id'],1,'10.0.0.1','a')
    for i,r in enumerate(d['entries']):
        s.checkin(lid,r['student_id'],i+1,teacher=True)
    assert s.detail(lid)['counts']['actual']==2


def test_restart_switch_round_and_class_isolation(app, active):
    s,lid,rows=lesson(app,active);s.action(lid,'open')
    s.checkin(lid,rows[0]['student_id'],1,'10.0.0.1','a')
    restarted=create_app(app.config['DATA_DIR'])
    assert restarted.extensions['attendance'].state()['counts']['actual']==1
    other=app.extensions['classes'].create('另一班')
    app.extensions['seating'].publish_class(other['id'])
    assert s.state()['lesson'] is None
    with pytest.raises(AppError):s.checkin(lid,rows[1]['student_id'],2,'10.0.0.2','b')
    app.extensions['seating'].publish_class(active[0]['id'])
    app.extensions['seating'].open_round(active[0]['id'])
    assert s.state()['lesson'] is None
    assert s.history(active[0]['id'])[0]['id']==lid
    assert not s.history(other['id'])


def test_teacher_security_recycle_restore_and_export(app,active):
    s,lid,rows=lesson(app,active);s.action(lid,'open')
    c=app.test_client();page=c.get('/',follow_redirects=True)
    token=re.search('name="csrf-token" content="([^"]+)"',page.text).group(1)
    headers={'Origin':'http://localhost','X-CSRF-Token':token}
    assert c.post('/api/v1/teacher/classes/manage',json={'ids':[active[0]['id']],'action':'delete'},headers=headers).status_code==403
    assert c.get('/teacher/attendance',environ_overrides={'REMOTE_ADDR':'10.0.0.1'}).status_code==403
    c.get('/teacher?key=test-bootstrap')
    assert c.post('/api/v1/teacher/lessons',json={},headers={**headers,'Origin':'http://evil'}).status_code==403
    export=c.get('/api/v1/teacher/lessons/'+lid+'/export')
    assert export.status_code==200 and export.data.startswith(b'\xef\xbb\xbf')
    response=c.post('/api/v1/teacher/classes/manage',json={'ids':[active[0]['id']],'action':'delete'},headers=headers)
    assert response.status_code==200
    assert not app.extensions['classes'].list() and s.state()['lesson'] is None
    assert s.detail(lid)['lesson']['ended_at']
    assert c.post('/api/v1/teacher/classes/manage',json={'ids':[active[0]['id']],'action':'restore'},headers=headers).status_code==200
    assert app.extensions['classes'].list()[0]['id']==active[0]['id']


def test_template_upgrade_preserves_records_devices_and_old_archive(tmp_path):
    root=tmp_path/'data';cfg=root/'config';cfg.mkdir(parents=True)
    legacy=Path('resources/templates/classroom-64-v1')
    for p in legacy.iterdir():shutil.copyfile(p,cfg/p.name)
    layout=json.loads((legacy/'layout.json').read_text(encoding='utf-8'))
    with sqlite3.connect(root/'classroom.sqlite3') as db:
        for _,sql in MIGRATIONS[:2]:db.executescript(sql)
        db.execute('PRAGMA user_version=2')
        db.execute("INSERT INTO classes VALUES ('c','Test','2026-09-01')")
        db.execute('INSERT INTO layouts VALUES (?,?)',(layout['id'],json.dumps(layout,ensure_ascii=False,sort_keys=True)))
        for i in (1,2):
            db.execute('INSERT INTO rounds(id,class_id,layout_id,number,opened_at,is_open,archived_at) VALUES (?,?,?,?,?,0,?)',(str(i)*32,'c',layout['id'],i,'2026-09-01','2026-09-01' if i==1 else None))
        db.execute("INSERT INTO seat_configs VALUES ('classroom-64-v1',4,1,'DEVICE','2026-09-01')")
    instance=create_app(root)
    seating=instance.extensions['seating']
    assert seating.get_arrangement('c')['layout']['id']=='classroom-64-v2'
    assert seating.get_arrangement('c','1'*32)['layout']['id']=='classroom-64-v1'
    assert next(x for x in seating.get_arrangement('c')['seat_configs'] if x['seat_no']==4)['disabled']
    instance.extensions['exports'].export('c','1'*32)
    assert len(list((root/'backups').glob('*.sqlite3')))==1
    assert (cfg/'seat-template.xlsx').read_bytes()==Path('resources/seat-template.xlsx').read_bytes()
