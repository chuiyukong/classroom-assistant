import sqlite3
from concurrent.futures import ThreadPoolExecutor
import pytest
from classroom.core.errors import AppError
from classroom.core.db import Database,MIGRATIONS
from tests.test_v120 import lesson
from tests.test_api import login


def test_start_is_exclusive_and_switch_requires_current_confirmation(app,active):
    attendance,lid,rows=lesson(app,active,50)
    attendance.action(lid,'open')
    attendance.checkin(lid,rows[0]['student_id'],1,'10.0.0.1','a')
    with pytest.raises(AppError):attendance.start(active[1]['id'])
    other=app.extensions['classes'].create('另一班')
    client,headers=login(app)
    url='/api/v1/teacher/classes/'+other['id']+'/publish'
    for payload in ({},{'expected_lesson_id':'stale'}):
        assert client.post(url,json=payload,headers=headers).status_code==409
        assert attendance.detail(lid)['lesson']['ended_at'] is None
    # Validation failure rolls back the end operation as well.
    with pytest.raises(AppError):attendance.publish_class('missing',lid)
    assert attendance.detail(lid)['lesson']['ended_at'] is None
    assert client.post(url,json={'expected_lesson_id':lid},headers=headers).status_code==200
    ended=attendance.detail(lid)
    assert ended['lesson']['ended_at'] and ended['lesson']['attendance_closed_at']
    assert ended['counts']['absent']==49 and ended['counts']['actual']==1
    assert app.extensions['seating'].get_current_arrangement()['active_class_id']==other['id']


def test_double_start_only_one_and_stale_lesson_can_end(app,active):
    seating=app.extensions['seating'];seating.correct(active[1]['id'],1,'测试生');seating.close_round(active[1]['id'])
    service=app.extensions['attendance']
    def start(_):
        try:return service.start(active[1]['id'])['lesson']['id']
        except AppError:return None
    with ThreadPoolExecutor(max_workers=2) as pool:result=list(pool.map(start,range(2)))
    assert sum(x is not None for x in result)==1
    lid=next(x for x in result if x)
    with app.extensions['database'].connect(write=True) as db:db.execute("UPDATE lessons SET started_at='2025-01-01T00:00:00+00:00' WHERE id=?",(lid,))
    assert service.state()['lesson']['id']==lid
    service.action(lid,'end')
    assert service.detail(lid)['lesson']['ended_at']


def test_roles_follow_student_public_projection_and_freeze_history(app,active):
    seating=app.extensions['seating'];rid=active[1]['id']
    seating.correct(rid,1,'测试班长',student_note='私密内容',role=3)
    sid=seating.get_current_arrangement()['registrations'][0]['student_id']
    public=seating.active('x','10.0.0.1')
    assert public['registrations'][0]['role']==3 and '私密内容' not in str(public)
    seating.close_round(rid);service=app.extensions['attendance'];lid=service.start(rid)['lesson']['id']
    assert service.state(True)['entries'][0]['role']==3
    seating.correct(rid,1,'测试班长',role=2)
    assert service.state(True)['entries'][0]['role']==2
    service.action(lid,'end')
    new=seating.open_round(active[0]['id'])['round']['id']
    seating.correct(new,2,'测试班长',student_id=sid,role=1)
    assert seating.get_arrangement(active[0]['id'],rid)['registrations'][0]['role']==2
    assert service.detail(lid)['entries'][0]['role']==2
    assert seating.get_current_arrangement()['registrations'][0]['role']==1
    with pytest.raises(AppError):seating.correct(new,2,'错误修改',role='monitor')
    assert seating.get_current_arrangement()['registrations'][0]['name']=='测试班长'
    client,headers=login(app)
    assert client.put('/api/v1/teacher/rounds/'+new+'/seats/2',json={'name':'测试班长','role':3},headers=headers,environ_overrides={'REMOTE_ADDR':'10.0.0.9'}).status_code==403


def test_schema7_upgrade_has_backup_and_no_guessed_roles(tmp_path):
    path=tmp_path/'classroom.sqlite3'
    with sqlite3.connect(path) as db:
        for version,sql in MIGRATIONS[:7]:db.executescript(sql)
        db.execute('PRAGMA user_version=7')
    Database(path).migrate()
    assert list((tmp_path/'backups').glob('*.sqlite3'))
    with Database(path).connect() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0]==8
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
        assert not db.execute('SELECT * FROM student_roles').fetchall()
