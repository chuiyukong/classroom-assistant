import csv
import io
import sqlite3
import pytest
from classroom.core.errors import AppError
from classroom.core.db import Database, MIGRATIONS
from classroom.exports.class_csv import ClassCsvExport
from tests.test_v120 import lesson
from tests.test_api import login


def test_graduation_is_fixed_and_old_grade_not_guessed(app):
    classes=app.extensions['classes']
    a=classes.create('一班',2026,'上学期',graduation_year=2029)
    b=classes.create('一班',2026,'上学期',graduation_year=2030)
    assert a['id']!=b['id']
    with pytest.raises(AppError):classes.set_graduation(b['id'],2029)
    old=classes.create('旧班',grade='高一')
    assert old['graduation_year']==0
    classes.set_graduation(old['id'],2028)
    assert next(c for c in classes.list() if c['id']==old['id'])['graduation_year']==2028
    for value in (True,'2029',202.5,99,3000):
        with pytest.raises(AppError):classes.set_graduation(old['id'],value)


def test_long_term_approval_persists_and_http_reads_new_fixed_seat(app,active):
    attendance,lid,rows=lesson(app,active,50);attendance.action(lid,'open')
    attendance.checkin(lid,rows[0]['student_id'],64,'10.0.0.64','student',move_reason='long_term')
    request=attendance.detail(lid)['change_requests'][0]
    client,headers=login(app)
    result=client.post('/api/v1/teacher/seat-changes/'+request['id'],json={'approve':True},headers=headers)
    assert result.status_code==200 and result.json['fixed_updated']
    assert result.json['registration']['seat_no']==64
    data=client.get('/api/v1/teacher/classes/'+active[0]['id']+'/arrangement').json
    assert next(r for r in data['registrations'] if r['student_id']==rows[0]['student_id'])['seat_no']==64
    with app.extensions['database'].connect() as db:
        assert db.execute('SELECT seat_no FROM registrations WHERE student_id=?',(rows[0]['student_id'],)).fetchone()[0]==64
        assert db.execute('SELECT status FROM seat_change_requests WHERE id=?',(request['id'],)).fetchone()[0]=='approved'


def test_notification_only_selected_device_and_expires(app,active):
    attendance,lid,rows=lesson(app,active,50);attendance.action(lid,'open');draw=app.extensions['rollcall']
    attendance.checkin(lid,rows[0]['student_id'],1,'10.0.0.1','a')
    state=draw.current();draw.draw_current(state['context_id'],expected_candidates=[rows[0]['student_id']])
    assert draw.student_announcement('10.0.0.1','a')['announcement']['name']==rows[0]['name']
    assert draw.student_announcement('10.0.0.2','b')['announcement'] is None
    with pytest.raises(AppError):draw.draw_current(state['context_id'],expected_candidates=['not-in-roster'])
    draw._announcement['expires']=0
    assert draw.student_announcement('10.0.0.1','a')['announcement'] is None


def test_class_csv_all_modules_isolated_and_formula_safe(app,active):
    attendance,lid,rows=lesson(app,active,50);attendance.action(lid,'open')
    attendance.checkin(lid,rows[0]['student_id'],64,'10.0.0.64','a',move_reason='device_fault')
    app.extensions['students'].update_note(rows[0]['student_id'],'=1+2')
    other=app.extensions['classes'].create('不应导出的班')
    exporter=ClassCsvExport(app.extensions['database'],app.extensions['classes'],app.extensions['seating'],attendance,app.extensions['rollcall'])
    content=exporter.export([active[0]['id']]).getvalue().decode('utf-8-sig')
    assert other['id'] not in content and "'=1+2" in content and '10.0.0.64' in content
    types={r['数据类型'] for r in csv.DictReader(io.StringIO(content))}
    assert {'班级','学生资料及备注','座位记录','课堂','考勤','换座申请','签到设备及纠正记录','教室布局','共用设备配置'}<=types
    client,headers=login(app)
    assert client.get('/api/v1/teacher/classes/export-csv?ids='+active[0]['id']).status_code==200
    assert client.get('/api/v1/teacher/classes/export-csv?ids='+active[0]['id'],environ_overrides={'REMOTE_ADDR':'10.0.0.8'}).status_code==403


def test_migration_6_to_7_keeps_class_references(tmp_path):
    path=tmp_path/'db.sqlite3'
    with sqlite3.connect(path) as db:
        for _,sql in MIGRATIONS[:6]:db.executescript(sql)
        db.execute("INSERT INTO classes(id,name,created_at,grade) VALUES ('c','一班','2026-09-01','高一')")
        db.execute("INSERT INTO students(id,class_id,name,name_key,created_at,updated_at) VALUES ('s','c','甲','甲','2026-09-01','2026-09-01')")
        db.execute('PRAGMA user_version=6')
    Database(path).migrate()
    with Database(path).connect() as db:
        assert db.execute('SELECT graduation_year FROM classes').fetchone()[0]==0
        assert db.execute('SELECT class_id FROM students').fetchone()[0]=='c'
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
