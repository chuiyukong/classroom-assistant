import secrets
from uuid import uuid4
from classroom.classes.service import timestamp
from classroom.core.errors import AppError


class RollCallService:
    def __init__(self, database, attendance):
        self.database, self.attendance = database, attendance

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
