"""Lesson snapshots and attendance. Never updates the seating module's records."""
from datetime import datetime, timezone, timedelta
from uuid import uuid4
from classroom.classes.service import timestamp
from classroom.core.errors import AppError
from classroom.seating.service import normalize_ip
from classroom.students.service import name_key

STATUSES = {'pending': '未签到', 'present': '已到', 'late': '迟到', 'leave': '请假', 'absent': '缺勤', 'long_leave': '长期请假'}


class AttendanceService:
    def __init__(self, database, seating):
        self.database, self.seating = database, seating

    def current(self, db, arrangement=None):
        data = arrangement if arrangement is not None else self.seating.get_current_arrangement(db)
        row = db.execute('SELECT * FROM lessons WHERE ended_at IS NULL').fetchone()
        if not row or not data['round'] or row['round_id'] != data['round']['id']:
            return None
        if datetime.fromisoformat(row['started_at']).astimezone().date() != datetime.now().astimezone().date():
            return None
        return dict(row)

    def start(self, expected_round_id, late_after=5):
        if type(late_after) is not int or not 0 <= late_after <= 40:
            raise AppError('迟到宽限须为 0—40 分钟的整数')
        with self.database.connect(write=True) as db:
            data = self.seating.get_current_arrangement(db)
            if not data['round'] or data['round']['id'] != expected_round_id or not data['registrations']:
                raise AppError('当前座位已变化或没有学生，请回到选座页面核对', 409)
            if data['round']['is_open']:
                raise AppError('请先结束座位登记，再开始本节课', 409)
            now = timestamp()
            db.execute("UPDATE attendance_entries SET status='absent' WHERE status='pending' AND lesson_id IN (SELECT id FROM lessons WHERE ended_at IS NULL AND attendance_started_at IS NOT NULL)")
            db.execute('UPDATE lessons SET ended_at=?, attendance_closed_at=CASE WHEN attendance_started_at IS NOT NULL THEN COALESCE(attendance_closed_at,?) END WHERE ended_at IS NULL', (now, now))
            lid = uuid4().hex
            db.execute('INSERT INTO lessons(id,class_id,round_id,class_name,started_at,late_after,layout_id) VALUES (?,?,?,?,?,?,?)', (lid, data['class']['id'], expected_round_id, data['class']['name'], now, late_after, data['layout']['id']))
            for r in data['registrations']:
                if not r['student_id']:
                    raise AppError('名单缺少学生编号，请重新登记', 409)
                leave = db.execute('SELECT 1 FROM attendance_leave WHERE student_id=?', (r['student_id'],)).fetchone()
                db.execute('INSERT INTO attendance_entries(lesson_id,student_id,name,original_seat,status) VALUES (?,?,?,?,?)', (lid, r['student_id'], r['name'], r['seat_no'], 'long_leave' if leave else 'pending'))
        return self.detail(lid)

    def require_current(self, db, lid):
        lesson = self.current(db)
        if not lesson or lesson['id'] != lid:
            raise AppError('本节课堂已结束或班级已切换，请刷新', 409)
        return lesson

    def action(self, lid, action, duration_minutes=10):
        with self.database.connect(write=True) as db:
            lesson = self.require_current(db, lid)
            now = timestamp()
            if action == 'open':
                if type(duration_minutes) is not int or not 1 <= duration_minutes <= 40:
                    raise AppError('签到时长须为 1—40 分钟的整数')
                if lesson['attendance_started_at']:
                    raise AppError('本节课已经发起过签到，请勿重复开始', 409)
                deadline = (datetime.fromisoformat(now) + timedelta(minutes=duration_minutes)).isoformat(timespec='seconds')
                db.execute('UPDATE lessons SET attendance_started_at=?,attendance_deadline=? WHERE id=?', (now, deadline, lid))
            elif action in ('close', 'end'):
                if lesson['attendance_started_at']:
                    db.execute("UPDATE attendance_entries SET status='absent' WHERE lesson_id=? AND status='pending'", (lid,))
                    db.execute('UPDATE lessons SET attendance_closed_at=COALESCE(attendance_closed_at,?) WHERE id=?', (now, lid))
                if action == 'end':
                    db.execute('UPDATE lessons SET ended_at=? WHERE id=?', (now, lid))
            else:
                raise AppError('无效课堂操作')
        return self.detail(lid)

    def detail(self, lid, connection=None):
        if connection is None:
            with self.database.connect() as db:
                return self.detail(lid, db)
        db = connection
        lesson = db.execute('SELECT * FROM lessons WHERE id=?', (lid,)).fetchone()
        if not lesson:
            raise AppError('课堂记录不存在', 404)
        rows = [dict(r) for r in db.execute('SELECT student_id,name,original_seat,seat_no,status,signed_at,late_seconds,move_reason FROM attendance_entries WHERE lesson_id=? ORDER BY original_seat', (lid,))]
        counts = {s: sum(r['status'] == s for r in rows) for s in STATUSES}
        counts.update(expected=len(rows), actual=counts['present'] + counts['late'])
        current = self.current(db)
        layout = self.seating.layouts.get(lesson['layout_id'], db)
        requests = [dict(r) for r in db.execute('SELECT q.*,e.name FROM seat_change_requests q JOIN attendance_entries e ON e.lesson_id=q.lesson_id AND e.student_id=q.student_id WHERE q.lesson_id=?', (lid,))]
        configs = self.seating.seats.read(db, layout['id'])
        return {'lesson': dict(lesson), 'entries': rows, 'counts': counts, 'is_current': bool(current and current['id'] == lid),
                'layout': layout, 'disabled_seats': [n for n,c in configs.items() if c['disabled']], 'change_requests': requests, 'server_time': timestamp()}

    def state(self, student=False, ip=None, client_id=None):
        with self.database.connect() as db:
            lesson = self.current(db)
            if not lesson:
                data = self.seating.get_current_arrangement(db)
                return {'lesson': None, 'layout': data['layout'], 'entries': [dict(student_id=r['student_id'],name=r['name'],original_seat=r['seat_no'],seat_no=None) for r in data['registrations']], 'disabled_seats': [s['seat_no'] for s in data['seat_configs'] if s['disabled']], 'server_time': timestamp()}
            result = self.detail(lesson['id'], db)
            if student:
                rows = result['entries']
                result.pop('counts')
                result.pop('change_requests')
                result['entries'] = [{'student_id': r['student_id'], 'name': r['name'], 'original_seat': r['original_seat'], 'seat_no': r['seat_no'], 'status': r['status'] if r['status'] in ('present','late','long_leave') else 'pending'} for r in rows]
                own = db.execute('SELECT student_id FROM attendance_entries WHERE lesson_id=? AND (source_ip=? OR client_id=?)', (lesson['id'], normalize_ip(ip), client_id)).fetchone()
                result['my_student_id'] = own[0] if own else None
                data = self.seating.get_current_arrangement(db)
                disabled = {s['seat_no'] for s in data['seat_configs'] if s['disabled']}
                occupied = {r['seat_no'] for r in rows if r['seat_no'] is not None}
                result['available_seats'] = [s['number'] for s in data['layout']['seats'] if s['number'] not in disabled | occupied]
            return result

    def checkin(self, lid, sid, seat, ip=None, client_id=None, teacher=False, name=None, move_reason=''):
        if (not isinstance(sid, str) and not isinstance(name, str)) or type(seat) is not int:
            raise AppError('请选择名单中的姓名和实际座位')
        with self.database.connect(write=True) as db:
            lesson = self.require_current(db, lid)
            if not lesson['attendance_started_at'] or (lesson['attendance_closed_at'] and not teacher):
                raise AppError('签到尚未开始或已经结束', 409)
            if name is not None:
                if not isinstance(name, str) or not name.strip() or len(name)>30:
                    raise AppError('请输入已登记的姓名')
                matches = [r for r in db.execute('SELECT student_id,name FROM attendance_entries WHERE lesson_id=?', (lid,)) if name_key(r['name']) == name_key(name)]
                if len(matches)!=1:
                    raise AppError('姓名未登记或存在同名，请联系教师', 409)
                if sid and sid != matches[0]['student_id']:
                    raise AppError('姓名与学生记录不一致', 409)
                sid = matches[0]['student_id']
            r = db.execute('SELECT * FROM attendance_entries WHERE lesson_id=? AND student_id=?', (lid, sid)).fetchone()
            if not r:
                raise AppError('该学生不在本节课座位名单中', 409)
            source_ip = normalize_ip(ip) if not teacher else None
            if not teacher and r['signed_at']:
                if r['seat_no'] == seat and (r['source_ip'] == source_ip or r['client_id'] == client_id):
                    return {'accepted': True, 'duplicate': True}
                raise AppError('此姓名已签到，请联系教师纠正', 409)
            if not teacher:
                if seat != r['original_seat'] and move_reason not in ('device_fault', 'long_term'):
                    raise AppError('请选择换座原因', 409, 'move_reason_required')
                same = [x for x in db.execute('SELECT name FROM attendance_entries WHERE lesson_id=?', (lid,)) if name_key(x['name']) == name_key(r['name'])]
                if len(same) > 1:
                    raise AppError('同名学生请到教师端签到', 409)
                if db.execute('SELECT 1 FROM attendance_entries WHERE lesson_id=? AND (source_ip=? OR client_id=?)', (lid, source_ip, client_id)).fetchone():
                    raise AppError('本机已完成本次签到，请联系教师', 409)
            data = self.seating.get_current_arrangement(db)
            disabled = {s['seat_no'] for s in data['seat_configs'] if s['disabled']}
            if seat not in {s['number'] for s in data['layout']['seats']} or seat in disabled:
                raise AppError('该座位不可用', 409)
            if db.execute('SELECT 1 FROM attendance_entries WHERE lesson_id=? AND seat_no=? AND student_id!=?', (lid, seat, sid)).fetchone():
                raise AppError('该座位已有同学签到，请选择实际空位', 409)
            now = timestamp()
            elapsed = max(0, int((datetime.fromisoformat(now) - datetime.fromisoformat(lesson['attendance_started_at'])).total_seconds()))
            # Legacy lessons without a deadline retain their recorded threshold.
            cutoff = datetime.fromisoformat(lesson['attendance_deadline']) if lesson['attendance_deadline'] else datetime.fromisoformat(lesson['attendance_started_at']) + timedelta(minutes=lesson['late_after'])
            late = max(0, int((datetime.fromisoformat(now) - cutoff).total_seconds()))
            is_late = datetime.fromisoformat(now) >= cutoff
            db.execute('UPDATE attendance_entries SET seat_no=?,status=?,signed_at=?,late_seconds=?,source_ip=?,client_id=? WHERE lesson_id=? AND student_id=?', (seat, 'late' if is_late else 'present', now, late, source_ip, None if teacher else client_id, lid, sid))
            db.execute('DELETE FROM attendance_leave WHERE student_id=?', (sid,))
            db.execute('UPDATE attendance_entries SET move_reason=? WHERE lesson_id=? AND student_id=?', (move_reason if seat != r['original_seat'] else '',lid,sid))
            db.execute("UPDATE seat_change_requests SET status='cancelled',decided_at=? WHERE lesson_id=? AND student_id=? AND status='pending'", (now,lid,sid))
            if not teacher and move_reason == 'long_term' and seat != r['original_seat']:
                db.execute('''INSERT INTO seat_change_requests VALUES (?,?,?,?,?,'pending',?,NULL)
                    ON CONFLICT(lesson_id,student_id) DO UPDATE SET from_seat=excluded.from_seat,to_seat=excluded.to_seat,status='pending',created_at=excluded.created_at,decided_at=NULL''', (uuid4().hex,lid,sid,r['original_seat'],seat,now))
        return {'accepted': True}

    def mark(self, lid, sid, status):
        if status not in ('pending', 'leave', 'absent', 'long_leave'):
            raise AppError('考勤状态无效；到场请使用教师补签')
        with self.database.connect(write=True) as db:
            lesson = self.require_current(db, lid)
            if not lesson['attendance_started_at']:
                raise AppError('请先发起签到', 409)
            if not db.execute('SELECT 1 FROM attendance_entries WHERE lesson_id=? AND student_id=?', (lid, sid)).fetchone():
                raise AppError('学生不在本次名单中', 404)
            db.execute('UPDATE attendance_entries SET status=?,seat_no=NULL,signed_at=NULL,late_seconds=0,source_ip=NULL,client_id=NULL WHERE lesson_id=? AND student_id=?', (status, lid, sid))
            db.execute('DELETE FROM attendance_leave WHERE student_id=?', (sid,))
            db.execute("UPDATE seat_change_requests SET status='cancelled',decided_at=? WHERE lesson_id=? AND student_id=? AND status='pending'", (timestamp(),lid,sid))
            if status == 'long_leave':
                db.execute('INSERT INTO attendance_leave VALUES (?,?,?)', (sid, lesson['class_id'], timestamp()))

    def decide_move(self, request_id, approve):
        if type(approve) is not bool:
            raise AppError('审批操作无效')
        with self.database.connect(write=True) as db:
            q = db.execute('SELECT * FROM seat_change_requests WHERE id=?',(request_id,)).fetchone()
            if not q:
                raise AppError('换座申请不存在',404)
            if q['status'] != 'pending':
                raise AppError('该申请已处理',409)
            lesson = self.require_current(db,q['lesson_id'])
            signed = db.execute('SELECT seat_no FROM attendance_entries WHERE lesson_id=? AND student_id=?',(q['lesson_id'],q['student_id'])).fetchone()
            if not signed or signed['seat_no'] != q['to_seat']:
                raise AppError('签到座位已变更，请核对',409)
            if approve:
                self.seating.approve_move(db,lesson['round_id'],q['student_id'],q['from_seat'],q['to_seat'])
            db.execute('UPDATE seat_change_requests SET status=?,decided_at=? WHERE id=?',('approved' if approve else 'rejected',timestamp(),request_id))

    def history(self, class_id=None, day=None):
        if day:
            try:
                datetime.strptime(day, '%Y-%m-%d')
            except ValueError:
                raise AppError('日期格式应为 YYYY-MM-DD')
        with self.database.connect() as db:
            return [dict(r) for r in db.execute("SELECT * FROM lessons WHERE (? IS NULL OR class_id=?) AND (? IS NULL OR date(started_at,'localtime')=?) ORDER BY started_at DESC,rowid DESC", (class_id, class_id, day, day))]

    def candidates(self, db, lid):
        lesson = self.require_current(db, lid)
        rows = db.execute('SELECT student_id,name,original_seat,seat_no,status FROM attendance_entries WHERE lesson_id=? ORDER BY original_seat', (lid,)).fetchall()
        source = 'attendance' if lesson['attendance_started_at'] else 'seating'
        return [{'student_id': r['student_id'], 'name': r['name'], 'seat_no': r['seat_no'] if source == 'attendance' else r['original_seat']} for r in rows if source == 'seating' or r['status'] in ('present', 'late')], source

    def retire_classes(self, db, ids):
        for cid in ids:
            db.execute("UPDATE attendance_entries SET status='absent' WHERE status='pending' AND lesson_id IN (SELECT id FROM lessons WHERE class_id=? AND ended_at IS NULL AND attendance_started_at IS NOT NULL)", (cid,))
            db.execute('UPDATE lessons SET ended_at=COALESCE(ended_at,?),attendance_closed_at=CASE WHEN attendance_started_at IS NOT NULL THEN COALESCE(attendance_closed_at,?) END WHERE class_id=?', (timestamp(), timestamp(), cid))
