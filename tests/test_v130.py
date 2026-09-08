from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import re
import shutil
from io import BytesIO
from openpyxl import load_workbook
import pytest
from classroom.core.config import prepare_data
from classroom.core.errors import AppError
from tests.test_v120 import lesson


def test_original_crlf_configuration_is_upgraded(tmp_path):
    root=tmp_path/'instance';config=root/'config';config.mkdir(parents=True)
    legacy=Path('resources/templates/classroom-64-v1')
    for name in ('layout.json','excel-template.json'):
        raw=(legacy/name).read_text(encoding='utf-8').replace('\n','\r\n')
        (config/name).write_bytes(raw.encode('utf-8'))
    shutil.copyfile(legacy/'seat-template.xlsx',config/'seat-template.xlsx')
    prepare_data(root)
    assert json.loads((config/'layout.json').read_text(encoding='utf-8'))['id']=='classroom-64-v2'
    assert (config/'seat-template.xlsx').read_bytes()==Path('resources/seat-template.xlsx').read_bytes()
    assert (config/'templates/classroom-64-v1/layout.json').read_bytes().count(b'\r\n')>0


def test_custom_config_is_not_silently_replaced(tmp_path):
    config=tmp_path/'config';config.mkdir()
    legacy=Path('resources/templates/classroom-64-v1')
    for p in legacy.iterdir():shutil.copyfile(p,config/p.name)
    data=json.loads((config/'layout.json').read_text(encoding='utf-8'));data['name']='Custom room'
    (config/'layout.json').write_text(json.dumps(data),encoding='utf-8')
    prepare_data(tmp_path)
    assert json.loads((config/'layout.json').read_text(encoding='utf-8'))==data


def test_deadline_is_server_enforced_and_persists(app,active):
    s,lid,rows=lesson(app,active)
    d=s.action(lid,'open',1)
    assert (datetime.fromisoformat(d['lesson']['attendance_deadline'])-datetime.fromisoformat(d['lesson']['attendance_started_at'])).total_seconds()==60
    with app.extensions['database'].connect(write=True) as db:
        db.execute('UPDATE lessons SET attendance_deadline=? WHERE id=?',((datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat(timespec='seconds'),lid))
    with pytest.raises(AppError,match='结束'):
        s.checkin(lid,rows[0]['student_id'],1,'10.0.0.1','a')
    state=s.state()
    assert state['lesson']['attendance_closed_at'] and state['counts']['absent']==3
    with app.extensions['database'].connect() as db:
        assert db.execute('SELECT attendance_closed_at FROM lessons WHERE id=?',(lid,)).fetchone()[0]
    s.checkin(lid,rows[0]['student_id'],1,teacher=True)
    assert s.detail(lid)['counts']['actual']==1


def test_name_reason_and_teacher_approval_preserve_identity_and_snapshot(app,active):
    s,lid,rows=lesson(app,active);s.action(lid,'open')
    with pytest.raises(AppError,match='未登记'):
        s.checkin(lid,None,64,'10.0.0.1','a',name='陌生人')
    with pytest.raises(AppError,match='原因'):
        s.checkin(lid,None,64,'10.0.0.1','a',name=rows[0]['name'])
    sid=rows[0]['student_id'];app.extensions['students'].update_note(sid,'PRIVATE-NOTE')
    s.checkin(lid,None,64,'10.0.0.1','a',name=rows[0]['name'],move_reason='long_term')
    q=s.detail(lid)['change_requests'][0]
    assert app.extensions['seating'].get_current_arrangement()['registrations'][0]['seat_no']==1
    public=json.dumps(s.state(True,'10.0.0.1','a'))
    assert 'change_requests' not in public and 'move_reason' not in public and 'PRIVATE' not in public
    s.decide_move(q['id'],True)
    current=app.extensions['seating'].get_current_arrangement()
    moved=next(r for r in current['registrations'] if r['student_id']==sid)
    assert moved['seat_no']==64 and moved['student_note']=='PRIVATE-NOTE'
    assert s.detail(lid)['entries'][0]['original_seat']==1
    cfg=json.loads((app.config['DATA_DIR']/'config/excel-template.json').read_text(encoding='utf-8'))
    result,_=app.extensions['exports'].export(active[0]['id']);sheet=load_workbook(result)['Sheet1']
    assert sheet[cfg['seat_cells']['64']].value==rows[0]['name']
    assert sheet[cfg['seat_cells']['1']].value in (None,'')
    with pytest.raises(AppError,match='已处理'):s.decide_move(q['id'],True)


def test_approval_cannot_overwrite_fixed_occupant_or_stale_registration(app,active):
    s,lid,rows=lesson(app,active);s.action(lid,'open')
    s.checkin(lid,None,2,'10.0.0.1','a',name=rows[0]['name'],move_reason='long_term')
    q=s.detail(lid)['change_requests'][0]
    with pytest.raises(AppError,match='不能覆盖'):s.decide_move(q['id'],True)
    assert s.detail(lid)['change_requests'][0]['status']=='pending'
    assert app.extensions['seating'].get_current_arrangement()['count']==3
    s.decide_move(q['id'],False)
    assert s.detail(lid)['change_requests'][0]['status']=='rejected'


def test_root_navigation_and_name_api_privileges(app,active):
    c=app.test_client()
    assert c.get('/').status_code==200
    s,lid,rows=lesson(app,active);s.action(lid,'open')
    assert c.get('/').location=='/attendance'
    page=c.get('/',follow_redirects=True)
    assert 'checkin-name' in page.text and 'checkin-student' not in page.text
    token=re.search('name="csrf-token" content="([^"]+)"',page.text).group(1)
    headers={'Origin':'http://localhost','X-CSRF-Token':token}
    payload=dict(lesson_id=lid,name=rows[0]['name'],seat_no=64,move_reason='long_term')
    assert c.post('/api/v1/student/attendance',json=payload,headers=headers).status_code==200
    q=s.detail(lid)['change_requests'][0]
    assert c.post('/api/v1/teacher/seat-changes/'+q['id'],json={'approve':True},headers=headers).status_code==403
    c.get('/teacher?key=test-bootstrap')
    assert c.post('/api/v1/teacher/seat-changes/'+q['id'],json={'approve':True},headers=headers).status_code==200


def test_roster_visible_without_open_lesson_and_readonly_history(app,active):
    s,lid,rows=lesson(app,active)
    s.action(lid,'end')
    d=s.state(True,'10.0.0.1','a')
    assert d['lesson'] is None and len(d['entries'])==3 and len(d['layout']['seats'])==64
    assert not d.get('available_seats')
    assert s.detail(lid)['is_current'] is False
