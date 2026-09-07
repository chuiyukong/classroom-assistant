from classroom.classes.service import timestamp
from classroom.core.errors import AppError
from classroom.students.service import clean_note


class SeatConfigService:
    """Physical device settings do not belong to classes or registration sessions."""
    def __init__(self, database, layouts):
        self.database, self.layouts = database, layouts

    def read(self, db, layout_id):
        physical_id = 'classroom-64-v2' if layout_id == 'classroom-64-v1' and self.layouts.current['id'] == 'classroom-64-v2' else layout_id
        stored = {r['seat_no']: dict(r) for r in db.execute('SELECT * FROM seat_configs WHERE layout_id=?', (physical_id,))}
        return {s['number']: stored.get(s['number'], {'seat_no': s['number'], 'disabled': False, 'note': ''})
                for s in self.layouts.get(layout_id, db)['seats']}

    def update(self, layout_id, seat_no, disabled, note):
        if type(disabled) is not bool:
            raise AppError('不可选状态必须为布尔值')
        note = clean_note(note)
        if layout_id != self.layouts.current['id']:
            raise AppError('只能修改当前教室设备配置', 409)
        if type(seat_no) is not int or seat_no not in {s['number'] for s in self.layouts.current['seats']}:
            raise AppError('座位号无效')
        with self.database.connect(write=True) as db:
            db.execute('''INSERT INTO seat_configs VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(layout_id, seat_no) DO UPDATE SET disabled=excluded.disabled,
                note=excluded.note, updated_at=excluded.updated_at''', (layout_id, seat_no, disabled, note, timestamp()))
