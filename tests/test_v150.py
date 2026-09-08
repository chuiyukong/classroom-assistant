import pytest
from classroom.core.errors import AppError
from tests.test_v120 import lesson


def test_rollcall_without_lesson_does_not_create_or_store_records(app, active):
    seating=app.extensions['seating'];draw=app.extensions['rollcall']
    for i in range(1,4):seating.correct(active[1]['id'],i,'测试'+str(i))
    state=draw.current();assert state['source']=='seating' and state['candidate_count']==3
    results=[draw.draw_current(state['context_id'])['student_id'] for _ in range(30)]
    assert all(a!=b for a,b in zip(results,results[1:]))
    with app.extensions['database'].connect() as db:
        assert db.execute('SELECT count(*) FROM lessons').fetchone()[0]==0
        assert db.execute('SELECT count(*) FROM rollcall_draws').fetchone()[0]==0


def test_attendance_candidates_and_context_switch(app,active):
    s,lid,rows=lesson(app,active);draw=app.extensions['rollcall']
    old=draw.current()['context_id'];s.action(lid,'open')
    data=draw.current();assert data['source']=='attendance' and data['candidate_count']==0
    with pytest.raises(AppError):draw.draw_current(old)
    with pytest.raises(AppError):draw.draw_current(data['context_id'])
    s.checkin(lid,rows[0]['student_id'],1,teacher=True)
    assert draw.current()['candidate_count']==1
    assert {draw.draw_current(data['context_id'])['student_id'] for _ in range(5)}=={rows[0]['student_id']}
    s.checkin(lid,rows[1]['student_id'],64,teacher=True)
    results=[draw.draw_current(data['context_id']) for _ in range(20)]
    assert {r['student_id'] for r in results}=={r['student_id'] for r in rows[:2]}
    assert all(a['student_id']!=b['student_id'] for a,b in zip(results,results[1:]))
    assert next(r for r in results if r['student_id']==rows[1]['student_id'])['seat_no']==64
    s.action(lid,'close');assert draw.current()['source']=='attendance'
    s.action(lid,'end');assert draw.current()['source']=='seating'


def test_public_long_leave_only_no_private_notes(app,active):
    s,lid,rows=lesson(app,active);s.action(lid,'open')
    app.extensions['students'].update_note(rows[0]['student_id'],'私密原因')
    s.mark(lid,rows[0]['student_id'],'long_leave')
    state=s.state(True,'10.0.0.1','a')
    assert state['entries'][0]['status']=='long_leave'
    assert '私密原因' not in str(state) and 'change_requests' not in state
    s.checkin(lid,rows[0]['student_id'],1,'10.0.0.1','a')
    assert s.state(True,'10.0.0.1','a')['entries'][0]['status']=='present'
    assert s.start(active[1]['id'])['entries'][0]['status']=='pending'
