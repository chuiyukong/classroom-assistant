import json
import secrets
from threading import Lock
from uuid import uuid4
from classroom.classes.service import timestamp
from classroom.core.errors import AppError


class RollCallService:
    def __init__(self, database, attendance):
        self.database, self.attendance = database, attendance
        self._lock = Lock()
        self._last_context = None
        self._last_student = None

    def current(self, connection=None, scope="all"):
        if connection is None:
            with self.database.connect() as db:
                return self.current(db,scope)
        arrangement = self.attendance.seating.get_current_arrangement(connection)
        lesson = self.attendance.current(connection, arrangement)
        data = self.attendance.detail(lesson['id'], connection) if lesson else {}
        if lesson and lesson['attendance_started_at']:
            source = 'attendance'
            entries = data['entries']
            candidates = [dict(student_id=r['student_id'], name=r['name'], seat_no=r['seat_no']) for r in entries if r['status'] in ('present','late')]
            context = 'attendance:' + lesson['id']
        else:
            source = 'seating'
            entries = [dict(student_id=r['student_id'],name=r['name'],original_seat=r['seat_no'],seat_no=None) for r in arrangement['registrations']]
            candidates = [dict(student_id=r['student_id'],name=r['name'],seat_no=r['original_seat']) for r in entries]
            context = 'seating:' + (arrangement['round']['id'] if arrangement['round'] else '')
            data['layout'] = arrangement['layout']
            data['disabled_seats'] = [r['seat_no'] for r in arrangement['seat_configs'] if r['disabled']]
        cid = arrangement['class']['id'] if arrangement['class'] else None
        saved = connection.execute('SELECT student_ids FROM rollcall_selections WHERE class_id=?',(cid,)).fetchone()
        roster = {r['student_id'] for r in entries}
        selected = [sid for sid in json.loads(saved[0]) if sid in roster] if saved else []
        if scope not in ('all','late','manual'):
            raise AppError('点名范围无效')
        if scope=='late':
            late_ids={r['student_id'] for r in entries if r.get('status')=='late'}
            candidates=[r for r in candidates if r['student_id'] in late_ids]
        elif scope=='manual':
            candidates=[r for r in candidates if r['student_id'] in selected]
        return dict(class_id=cid,scope=scope,selected_ids=selected,layout=data['layout'],disabled_seats=data['disabled_seats'],entries=entries,
                    source=source,context_id=context,candidates=candidates,candidate_count=len(candidates))

    def draw_current(self, expected_context, scope="all"):
        # UI draws are transient. A single previous identity prevents immediate repeats.
        with self._lock:
            data = self.current(scope=scope)
            if expected_context != data['context_id']:
                raise AppError('点名名单已切换，请重试',409)
            candidates = data['candidates']
            if not candidates:
                raise AppError('暂无可点名学生；已发起考勤时只使用已签到名单',409)
            pool = [r for r in candidates if r['student_id'] != self._last_student] if self._last_context == expected_context and len(candidates)>1 else candidates
            chosen = secrets.choice(pool)
            self._last_context, self._last_student = expected_context, chosen['student_id']
            return dict(chosen,source=data['source'],context_id=expected_context,candidate_count=len(candidates))

    def save_selection(self, expected_context, student_ids):
        if not isinstance(student_ids,list) or len(student_ids)>64 or any(not isinstance(s,str) for s in student_ids):
            raise AppError('请选择学生范围')
        with self.database.connect(write=True) as db:
            data=self.current(db)
            if data['context_id']!=expected_context or not data['class_id']:
                raise AppError('班级或名单已切换，请重新选择',409)
            roster={r['student_id'] for r in data['entries']}
            if any(s not in roster for s in student_ids):
                raise AppError('范围包含当前名单之外的学生',409)
            db.execute('INSERT INTO rollcall_selections VALUES (?,?,?) ON CONFLICT(class_id) DO UPDATE SET student_ids=excluded.student_ids,updated_at=excluded.updated_at',
                       (data['class_id'],json.dumps(list(dict.fromkeys(student_ids))),timestamp()))
        return self.current(scope='manual')

    def draw(self, lid):
        with self.database.connect(write=True) as db:
            candidates, source = self.attendance.candidates(db, lid)
            if not candidates:
                raise AppError('当前没有可点名学生；已发起签到时仅抽取已签到人员', 409)
            chosen = secrets.choice(candidates)
            result = dict(chosen, id=uuid4().hex, lesson_id=lid, source=source, created_at=timestamp())
            db.execute('INSERT INTO rollcall_draws VALUES (:id,:lesson_id,:student_id,:name,:seat_no,:source,:created_at)', result)
            return result

    def history(self, lid):
        with self.database.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM rollcall_draws WHERE lesson_id=? ORDER BY rowid DESC', (lid,))]
