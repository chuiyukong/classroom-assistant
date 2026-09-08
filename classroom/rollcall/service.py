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

    def current(self, connection=None):
        if connection is None:
            with self.database.connect() as db:
                return self.current(db)
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
        return dict(layout=data['layout'],disabled_seats=data['disabled_seats'],entries=entries,
                    source=source,context_id=context,candidates=candidates,candidate_count=len(candidates))

    def draw_current(self, expected_context):
        # UI draws are transient. A single previous identity prevents immediate repeats.
        with self._lock:
            data = self.current()
            if expected_context != data['context_id']:
                raise AppError('点名名单已切换，请重试',409)
            candidates = data['candidates']
            if not candidates:
                raise AppError('暂无可点名学生；已发起考勤时只使用已签到名单',409)
            pool = [r for r in candidates if r['student_id'] != self._last_student] if self._last_context == expected_context and len(candidates)>1 else candidates
            chosen = secrets.choice(pool)
            self._last_context, self._last_student = expected_context, chosen['student_id']
            return dict(chosen,source=data['source'],context_id=expected_context,candidate_count=len(candidates))

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
