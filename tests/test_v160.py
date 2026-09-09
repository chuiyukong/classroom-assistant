from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
import sqlite3
import pytest
from classroom.core.db import MIGRATIONS, Database
from classroom.core.errors import AppError
from classroom.web.app import create_app
from tests.test_v120 import lesson
from tests.test_api import login


def test_scoped_recheckin_survives_restart_and_logs_devices(app, active):
    s,lid,rows=lesson(app,active);s.action(lid,'open')
    sid=rows[0]['student_id']
    s.checkin(lid,sid,1,'10.0.0.1','old')
    original=s.detail(lid)['entries'][0]['signed_at']
    s.action(lid,'close');s.mark(lid,sid,'pending')
    with app.extensions['database'].connect(write=True) as db:
        db.execute('UPDATE lessons SET attendance_deadline=? WHERE id=?',((datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat(),lid))
    restarted=type(s)(app.extensions['database'],app.extensions['seating'])
    assert restarted.state(True,'10.0.0.64','new')['recheckin_available']
    with pytest.raises(AppError):restarted.checkin(lid,rows[1]['student_id'],2,'10.0.0.2','b')
    restarted.checkin(lid,sid,64,'10.0.0.64','new',move_reason='device_fault')
    row=restarted.detail(lid)['entries'][0]
    assert row['seat_no']==64 and row['source_ip']=='10.0.0.64' and not row['recheckin_allowed']
    assert row['first_signed_at']==original
    assert [e['source_ip'] for e in restarted.events(lid)]==['10.0.0.1','10.0.0.1','10.0.0.64']
    public=restarted.state(True,'10.0.0.64','new')
    assert public['my_student_id']==sid and 'source_ip' not in str(public)
    restarted.mark(lid,sid,'pending');restarted.action(lid,'end')
    with pytest.raises(AppError):restarted.checkin(lid,sid,63,'10.0.0.63','last',move_reason='device_fault')


def test_temporary_approval_and_long_move_keep_separate_boundaries(app,active):
    s,lid,rows=lesson(app,active);s.action(lid,'open');sid=rows[0]['student_id']
    s.checkin(lid,sid,64,'10.0.0.64','x',move_reason='device_fault')
    q=s.detail(lid)['change_requests'][0];assert q['kind']=='temporary'
    s.decide_move(q['id'],True)
    assert app.extensions['seating'].get_current_arrangement()['registrations'][0]['seat_no']==1
    assert s.detail(lid)['entries'][0]['seat_no']==64
    s.mark(lid,sid,'pending');s.checkin(lid,sid,63,'10.0.0.63','y',move_reason='long_term')
    q=s.detail(lid)['change_requests'][0];assert q['kind']=='long_term'
    s.decide_move(q['id'],True)
    assert next(r for r in app.extensions['seating'].get_current_arrangement()['registrations'] if r['student_id']==sid)['seat_no']==63
    s.mark(lid,sid,'pending');s.checkin(lid,sid,62,'10.0.0.62','z',move_reason='long_term')
    q=s.detail(lid)['change_requests'][0];assert q['from_seat']==63
    s.decide_move(q['id'],True)


def test_rollcall_scopes_persist_by_class_filter_absent_and_reject_stale(app,active):
    s,lid,rows=lesson(app,active);draw=app.extensions['rollcall']
    context=draw.current()['context_id'];ids=[r['student_id'] for r in rows[:2]]
    draw.save_selection(context,ids)
    assert type(draw)(app.extensions['database'],s).current(scope='manual')['candidate_count']==2
    s.action(lid,'open');s.checkin(lid,ids[0],1,'10.0.0.1','a')
    assert draw.current(scope='manual')['candidate_count']==1
    with app.extensions['database'].connect(write=True) as db:
        db.execute('UPDATE lessons SET attendance_deadline=? WHERE id=?',((datetime.now(timezone.utc)-timedelta(seconds=5)).isoformat(),lid))
    s.checkin(lid,ids[1],2,'10.0.0.2','b')
    data=draw.current(scope='late');assert data['candidate_count']==1
    assert draw.draw_current(data['context_id'],'late')['student_id']==ids[1]
    with pytest.raises(AppError):draw.save_selection(context,ids)
    with pytest.raises(AppError):draw.save_selection(data['context_id'],['foreign'])
    c=app.extensions['classes'].create('第二班');app.extensions['seating'].open_round(c['id'])
    assert draw.current(scope='manual')['selected_ids']==[]


def test_log_ips_times_grade_and_permissions(app,active):
    app.extensions['classes'].set_grade(active[0]['id'],'高一')
    s,lid,rows=lesson(app,active);s.action(lid,'open')
    s.checkin(lid,rows[0]['student_id'],1,'10.0.0.1','x');s.action(lid,'end')
    assert len(s.history(grade='高一'))==1 and s.history(grade='高二')==[]
    client,headers=login(app)
    csv=client.get('/api/v1/teacher/lessons/'+lid+'/export').data.decode('utf-8-sig')
    assert '学生机IP' in csv and '10.0.0.1' in csv and '下课时间' in csv
    assert s.detail(lid)['lesson']['ended_at']
    assert client.get('/teacher/data').status_code==200
    remote={'REMOTE_ADDR':'10.0.0.2'}
    assert client.get('/api/v1/teacher/lessons/'+lid+'/events',environ_overrides=remote).status_code==403
    assert client.put('/api/v1/teacher/rollcall/selection',json={},headers=headers,environ_overrides=remote).status_code==403


def test_schema5_upgrade_backup_and_defaults(tmp_path):
    path=tmp_path/'classroom.sqlite3'
    with sqlite3.connect(path) as db:
        for version,sql in MIGRATIONS[:5]:db.executescript(sql)
        db.execute("INSERT INTO classes(id,name,created_at) VALUES ('c','测试','2026-09-08')")
        db.execute('PRAGMA user_version=5')
    Database(path).migrate()
    assert list((tmp_path/'backups').glob('*.sqlite3'))
    with Database(path).connect() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0]==7
        assert db.execute('SELECT grade FROM classes').fetchone()[0]==''
        assert not db.execute('PRAGMA foreign_key_check').fetchall()


def test_fifty_students_concurrent_attendance_and_lesson_isolation(app,active,monkeypatch):
    # Test concurrency independently of the intentional local-midnight boundary.
    moment=datetime.now(timezone.utc)
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls,tz=None):
            return moment.astimezone(tz) if tz else moment.astimezone().replace(tzinfo=None)
    monkeypatch.setattr('classroom.attendance.service.datetime',FrozenDateTime)
    monkeypatch.setattr('classroom.attendance.service.timestamp',lambda:moment.isoformat(timespec='seconds'))
    s,lid,rows=lesson(app,active,50);s.action(lid,'open')
    def sign(pair):
        number,row=pair
        return s.checkin(lid,row['student_id'],number,'10.2.0.'+str(number),'device-'+str(number))
    with ThreadPoolExecutor(max_workers=50) as pool:
        results=list(pool.map(sign,enumerate(rows,1)))
    assert all(r['accepted'] for r in results)
    data=s.detail(lid)
    assert data['counts']['expected']==data['counts']['actual']==50
    assert len({r['source_ip'] for r in data['entries']})==50
    assert len(s.events(lid))==50
    s.action(lid,'end');next_lesson=s.start(active[1]['id'])
    assert next_lesson['counts']['pending']==50 and next_lesson['counts']['actual']==0
    assert s.detail(lid)['counts']['actual']==50
