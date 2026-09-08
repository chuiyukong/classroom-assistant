from datetime import datetime, timedelta
import sqlite3
import pytest
from classroom.core.errors import AppError
from classroom.core.db import MIGRATIONS, Database
from classroom.classes.service import ClassService
from classroom.web.app import create_app
from tests.test_v120 import lesson


def test_deadline_boundary_retry_restart_and_manual_close(app, active, monkeypatch):
    service,lid,rows=lesson(app,active)
    d=service.action(lid,'open',1)
    cutoff=datetime.fromisoformat(d['lesson']['attendance_deadline'])
    monkeypatch.setattr('classroom.attendance.service.timestamp',lambda:(cutoff-timedelta(seconds=1)).isoformat(timespec='seconds'))
    service.checkin(lid,rows[0]['student_id'],1,'10.0.0.1','a')
    monkeypatch.setattr('classroom.attendance.service.timestamp',lambda:cutoff.isoformat(timespec='seconds'))
    service.checkin(lid,rows[1]['student_id'],2,'10.0.0.2','b')
    monkeypatch.setattr('classroom.attendance.service.timestamp',lambda:(cutoff+timedelta(seconds=125)).isoformat(timespec='seconds'))
    assert service.checkin(lid,rows[1]['student_id'],2,'10.0.0.2','b')['duplicate']
    service.checkin(lid,rows[2]['student_id'],3,'10.0.0.3','c')
    entries=service.detail(lid)['entries']
    assert [r['status'] for r in entries]==['present','late','late']
    assert [r['late_seconds'] for r in entries]==[0,0,125]
    restarted=create_app(app.config['DATA_DIR'])
    try:
        assert restarted.extensions['attendance'].state()['lesson']['attendance_closed_at'] is None
        assert restarted.extensions['attendance'].state()['counts']['late']==2
    finally:
        for handler in list(restarted.logger.handlers):
            if hasattr(handler,'baseFilename'):restarted.logger.removeHandler(handler);handler.close()
    service.action(lid,'close')
    with pytest.raises(AppError):service.checkin(lid,rows[2]['student_id'],3,'10.0.0.3','c')


def test_semester_isolation_validation_and_recycle(app):
    classes=app.extensions['classes']
    first=classes.create('高一（1）班',2026,'上学期')
    second=classes.create('高一（1）班',2026,'下学期')
    third=classes.create('高一（1）班',2027,'上学期')
    assert len({first['id'],second['id'],third['id']})==3
    for year,term in [(True,'上学期'),(2026,''),(0,'上学期'),(1999,'上学期'),(2026,'秋')]:
        with pytest.raises(AppError):classes.create('非法',year,term)
    with app.extensions['database'].connect(write=True) as db:classes.set_deleted(db,[first['id']],True)
    with pytest.raises(AppError):classes.create('高一（1）班',2026,'上学期')
    assert classes.list()[0]['year']==2027
    assert classes.list(True)[0]['id']==first['id']


def test_schema4_upgrade_keeps_foreign_keys_and_backup(tmp_path):
    path=tmp_path/'classroom.sqlite3'
    with sqlite3.connect(path) as db:
        for _,sql in MIGRATIONS[:4]:db.executescript(sql)
        db.execute("INSERT INTO classes VALUES ('old','旧班','2026-09-01',NULL)")
        db.execute("INSERT INTO students VALUES ('s','old','演示','演示','私密','2026','2026')")
        db.execute('PRAGMA user_version=4')
    database=Database(path);database.migrate()
    with database.connect() as db:
        assert db.execute('PRAGMA foreign_key_check').fetchall()==[]
        assert db.execute('SELECT year,semester FROM classes').fetchone()[:]==(0,'')
        assert db.execute('SELECT class_id FROM students').fetchone()[0]=='old'
    assert len(list((tmp_path/'backups').glob('*.sqlite3')))==1
    assert ClassService(database).create('旧班',2026,'上学期')['name']=='旧班'
