"""Current arrangements and archives. v1 storage/API 'round' names stay compatible."""
import ipaddress
from uuid import uuid4
from classroom.classes.service import timestamp
from classroom.core.errors import AppError, clean_text
from classroom.layouts.seats import SeatConfigService
from classroom.students.service import StudentService, clean_note, name_key

UNSET = object()


def normalize_ip(value):
    if value is None:
        return None  # Trusted internal calls may lack transport metadata.
    try:
        ip = ipaddress.ip_address(value)
        return str(getattr(ip, 'ipv4_mapped', None) or ip)
    except ValueError:
        raise AppError('无法识别设备地址，请联系教师')


class SeatingService:
    def __init__(self, database, layouts, limit_ip=True):
        self.database, self.layouts, self.limit_ip = database, layouts, limit_ip
        self.seats = SeatConfigService(database, layouts)
        self.students = StudentService(database)
        if layouts.current['id'] == 'classroom-64-v2':
            with database.connect(write=True) as db:
                # Same physical 64 seats; only current display groups/template changed.
                # Archived layouts are immutable and retain the original export.
                db.execute("UPDATE rounds SET layout_id='classroom-64-v2' WHERE layout_id='classroom-64-v1' AND archived_at IS NULL")

    def rounds(self, class_id):
        with self.database.connect() as db:
            self._class(db, class_id)
            return [dict(r) for r in db.execute('SELECT * FROM rounds WHERE class_id=? ORDER BY number DESC', (class_id,))]

    def publish_class(self, class_id):
        with self.database.connect(write=True) as db:
            self._class(db, class_id)
            opened = db.execute('SELECT class_id FROM rounds WHERE is_open=1').fetchone()
            if opened and opened['class_id'] != class_id:
                raise AppError('请先结束其他班级正在进行的登记，再切换上课班级', 409)
            db.execute('UPDATE classroom_state SET active_class_id=? WHERE singleton=1', (class_id,))

    def open_round(self, class_id, expected_current_id=UNSET):
        with self.database.connect(write=True) as db:
            self._class(db, class_id)
            opened = db.execute('SELECT c.name, c.id FROM rounds r JOIN classes c ON c.id=r.class_id WHERE r.is_open=1').fetchone()
            if opened and opened['id'] != class_id:
                raise AppError(f'请先选择“{opened["name"]}”并结束其当前登记，再发起新登记', 409, 'round_already_open')
            previous = db.execute('SELECT * FROM rounds WHERE class_id=? ORDER BY number DESC LIMIT 1', (class_id,)).fetchone()
            if expected_current_id is not UNSET and expected_current_id != (previous['id'] if previous else None):
                raise AppError('当前座位已变更，请刷新后重试', 409, 'stale_arrangement')
            now = timestamp()
            if previous:
                db.execute('''UPDATE registrations SET student_note=COALESCE(
                    (SELECT note FROM students WHERE students.id=registrations.student_id), student_note)
                    WHERE round_id=?''', (previous['id'],))
                db.execute('UPDATE rounds SET is_open=0, closed_at=COALESCE(closed_at, ?), archived_at=? WHERE id=?',
                           (now, now, previous['id']))
            number = previous['number'] + 1 if previous else 1
            db.execute('''INSERT INTO rounds(id, class_id, layout_id, number, opened_at, is_open)
                VALUES (?, ?, ?, ?, ?, 1)''', (uuid4().hex, class_id, self.layouts.current['id'], number, now))
            db.execute('UPDATE classroom_state SET active_class_id=? WHERE singleton=1', (class_id,))
        return self.get_arrangement(class_id)

    def close_round(self, round_id):
        with self.database.connect(write=True) as db:
            row = self._round(db, round_id)
            self._require_current(db, row)
            db.execute('UPDATE rounds SET is_open=0, closed_at=COALESCE(closed_at, ?) WHERE id=?', (timestamp(), round_id))

    def active(self, client_id, source_ip=None):
        """Student-safe projection; private notes and IP addresses are removed."""
        ip = normalize_ip(source_ip)
        with self.database.connect() as db:
            class_id = db.execute('SELECT active_class_id FROM classroom_state WHERE singleton=1').fetchone()[0]
            row = db.execute('SELECT * FROM rounds WHERE class_id=? ORDER BY number DESC LIMIT 1', (class_id,)).fetchone() if class_id else None
            result = self._arrangement(db, row) if row else self._empty(db, class_id)
            if row:
                own = db.execute('''SELECT seat_no FROM registrations WHERE round_id=?
                    AND (client_id=? OR (? AND source_ip=?)) ORDER BY seat_no LIMIT 1''',
                                 (row['id'], client_id, self.limit_ip, ip)).fetchone()
                result['my_seat'] = own[0] if own else None
            for record in result['registrations']:
                record.pop('student_note', None)
                record.pop('source_ip', None)
            for config in result['seat_configs']:
                config.pop('note', None)
                config.pop('updated_at', None)
            return result

    def get_current_arrangement(self, connection=None):
        """Shared teacher-side context for future attendance / roll call."""
        if connection is not None:
            db = connection
            cid = db.execute('SELECT active_class_id FROM classroom_state WHERE singleton=1').fetchone()[0]
            row = db.execute('SELECT * FROM rounds WHERE class_id=? ORDER BY number DESC LIMIT 1', (cid,)).fetchone() if cid else None
            return self._arrangement(db, row) if row else self._empty(db, cid)
        with self.database.connect() as db:
            cid = db.execute('SELECT active_class_id FROM classroom_state WHERE singleton=1').fetchone()[0]
            row = db.execute('SELECT * FROM rounds WHERE class_id=? ORDER BY number DESC LIMIT 1', (cid,)).fetchone() if cid else None
            return self._arrangement(db, row) if row else self._empty(db, cid)

    def get_arrangement(self, class_id, round_id=None):
        with self.database.connect() as db:
            self._class(db, class_id)
            if round_id:
                row = self._round(db, round_id)
                if row['class_id'] != class_id:
                    raise AppError('该存档不属于所选班级', 404)
            else:
                row = db.execute('SELECT * FROM rounds WHERE class_id=? ORDER BY number DESC LIMIT 1', (class_id,)).fetchone()
            return self._arrangement(db, row) if row else self._empty(db, class_id)

    def submit(self, round_id, seat_no, name, client_id, request_id, source_ip=None):
        name = clean_text(name, '姓名', 30)
        request_id = clean_text(request_id, '请求编号', 100)
        ip = normalize_ip(source_ip)
        with self.database.connect(write=True) as db:
            row = self._round(db, round_id)
            self._seat(db, row, seat_no)
            prior = db.execute('SELECT * FROM submissions WHERE round_id=? AND client_id=? AND request_id=?',
                               (round_id, client_id, request_id)).fetchone()
            if prior:
                if prior['seat_no'] != seat_no or prior['name'] != name:
                    raise AppError('重复请求的内容不同，请刷新页面', 409, 'request_reused')
                return {'accepted': True, 'duplicate': True, 'registration_id': prior['registration_id']}
            if not row['is_open']:
                raise AppError('登记已结束，请联系教师', 409, 'round_closed')
            if self.seats.read(db, row['layout_id'])[seat_no]['disabled']:
                raise AppError('该座位设备已停用，请选择可用座位或联系教师', 409, 'seat_disabled')
            if db.execute('SELECT 1 FROM registrations WHERE round_id=? AND seat_no=?', (round_id, seat_no)).fetchone():
                raise AppError('该座位已登记，请核对实际座位或联系教师', 409, 'seat_taken')
            if self.limit_ip and ip and db.execute('SELECT 1 FROM registrations WHERE round_id=? AND source_ip=?', (round_id, ip)).fetchone():
                raise AppError('这台电脑已完成本次登记，切换浏览器也不能重复登记；如需修改请联系教师', 409, 'device_registered')
            if db.execute('SELECT 1 FROM registrations WHERE round_id=? AND client_id=?', (round_id, client_id)).fetchone():
                raise AppError('本浏览器已经登记，请联系教师修改', 409, 'already_registered')
            if any(name_key(r['name']) == name_key(name) for r in db.execute('SELECT name FROM registrations WHERE round_id=?', (round_id,))):
                raise AppError('当前座位已存在同名学生，请到教师端登记', 409, 'duplicate_name')
            sid = self.students.resolve(db, row['class_id'], name, student_submission=True)
            record_id = uuid4().hex
            db.execute('''INSERT INTO registrations(id, round_id, seat_no, name, client_id, updated_at, source_ip, ip_key, student_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                       (record_id, round_id, seat_no, name, client_id, timestamp(), ip, ip if self.limit_ip else None, sid))
            db.execute('INSERT INTO submissions VALUES (?, ?, ?, ?, ?, ?)',
                       (round_id, client_id, request_id, seat_no, name, record_id))
            return {'accepted': True, 'duplicate': False, 'registration_id': record_id}

    def correct(self, round_id, seat_no, name, student_note=UNSET, student_id=None, force_new=False):
        if name != '':
            name = clean_text(name, '姓名', 30)
        if student_note is not UNSET:
            student_note = clean_note(student_note)
        if type(force_new) is not bool:
            raise AppError('新学生标记必须为布尔值')
        with self.database.connect(write=True) as db:
            row = self._round(db, round_id)
            self._require_current(db, row)
            self._seat(db, row, seat_no)
            existing = db.execute('SELECT * FROM registrations WHERE round_id=? AND seat_no=?', (round_id, seat_no)).fetchone()
            if name == '':
                db.execute('DELETE FROM registrations WHERE round_id=? AND seat_no=?', (round_id, seat_no))
                return
            if not existing and self.seats.read(db, row['layout_id'])[seat_no]['disabled']:
                raise AppError('该设备已停用，请先恢复可选状态再补填学生', 409, 'seat_disabled')
            sid = self.students.resolve(db, row['class_id'], name, student_id=student_id, force_new=force_new,
                                        current=existing['student_id'] if existing else None)
            used = db.execute('SELECT seat_no FROM registrations WHERE round_id=? AND student_id=? AND seat_no!=?',
                              (round_id, sid, seat_no)).fetchone()
            if used:
                raise AppError(f'此学生记录已在 {used[0]} 号座位；若为另一位同名学生，请勾选“同名新学生”', 409, 'student_registered')
            if student_note is not UNSET:
                db.execute('UPDATE students SET note=?, updated_at=? WHERE id=?', (student_note, timestamp(), sid))
            if existing:
                db.execute('UPDATE registrations SET name=?, student_id=?, updated_at=? WHERE id=?', (name, sid, timestamp(), existing['id']))
            else:
                db.execute('''INSERT INTO registrations(id, round_id, seat_no, name, updated_at, student_id)
                    VALUES (?, ?, ?, ?, ?, ?)''', (uuid4().hex, round_id, seat_no, name, timestamp(), sid))

    def _empty(self, db, class_id=None):
        return {'class': dict(self._class(db, class_id)) if class_id else None, 'round': None,
                'layout': self.layouts.current, 'registrations': [], 'count': 0, 'is_current': True,
                'seat_configs': list(self.seats.read(db, self.layouts.current['id']).values()),
                'active_class_id': db.execute('SELECT active_class_id FROM classroom_state WHERE singleton=1').fetchone()[0]}

    def _arrangement(self, db, row):
        layout = self.layouts.get(row['layout_id'], db)
        groups = {s['number']: s['group'] for s in layout['seats']}
        records = [dict(r) for r in db.execute('''SELECT g.id, g.seat_no, g.name, g.updated_at, g.student_id, g.source_ip,
            CASE WHEN ? IS NULL THEN COALESCE(s.note, g.student_note) ELSE g.student_note END AS student_note
            FROM registrations g LEFT JOIN students s ON s.id=g.student_id WHERE g.round_id=? ORDER BY g.seat_no''',
                                             (row['archived_at'], row['id']))]
        for record in records:
            record['group'] = groups[record['seat_no']]
        return {'class': dict(self._class(db, row['class_id'])), 'round': dict(row), 'layout': layout,
                'registrations': records, 'count': len(records), 'is_current': row['archived_at'] is None,
                'seat_configs': list(self.seats.read(db, row['layout_id']).values()),
                'active_class_id': db.execute('SELECT active_class_id FROM classroom_state WHERE singleton=1').fetchone()[0]}

    @staticmethod
    def _class(db, class_id):
        row = db.execute('SELECT * FROM classes WHERE id=? AND deleted_at IS NULL', (class_id,)).fetchone()
        if not row:
            raise AppError('班级不存在', 404)
        return row

    def retire_classes(self, db, ids):
        for cid in ids:
            db.execute('UPDATE rounds SET is_open=0, closed_at=COALESCE(closed_at,?) WHERE class_id=?', (timestamp(), cid))
            db.execute('UPDATE classroom_state SET active_class_id=NULL WHERE active_class_id=?', (cid,))

    def approve_move(self, db, round_id, student_id, from_seat, to_seat):
        """Explicit teacher approval; keep identity, notes and historical seats intact."""
        row = self._round(db, round_id)
        self._require_current(db, row)
        if row['is_open']:
            raise AppError('请先结束座位登记，再批准长期换座', 409)
        self._seat(db, row, to_seat)
        current = db.execute('SELECT * FROM registrations WHERE round_id=? AND student_id=?', (round_id, student_id)).fetchone()
        if not current or current['seat_no'] != from_seat:
            raise AppError('该生当前座位已变更，请重新核对申请', 409)
        if self.seats.read(db, row['layout_id'])[to_seat]['disabled']:
            raise AppError('目标设备已停用，请先修复或选择其他座位', 409)
        if db.execute('SELECT 1 FROM registrations WHERE round_id=? AND seat_no=?', (round_id, to_seat)).fetchone():
            raise AppError('目标座位已有固定登记，请先在在线选座中调整，不能覆盖其他学生', 409)
        db.execute('UPDATE registrations SET seat_no=?,updated_at=? WHERE id=?', (to_seat, timestamp(), current['id']))
        saved=db.execute('SELECT student_id,seat_no FROM registrations WHERE id=?',(current['id'],)).fetchone()
        if not saved or saved['seat_no']!=to_seat:
            raise AppError('固定座位保存未完成，请重试',409)
        return dict(saved)

    @staticmethod
    def _round(db, round_id):
        if not isinstance(round_id, str) or len(round_id) != 32:
            raise AppError('登记编号无效')
        row = db.execute('SELECT * FROM rounds WHERE id=?', (round_id,)).fetchone()
        if not row:
            raise AppError('登记或存档不存在', 404)
        SeatingService._class(db, row['class_id'])
        return row

    @staticmethod
    def _require_current(db, row):
        if row['archived_at'] is not None:
            raise AppError('历史存档只读，请选择当前座位', 409, 'history_readonly')

    def _seat(self, db, row, seat_no):
        if type(seat_no) is not int or seat_no not in {s['number'] for s in self.layouts.get(row['layout_id'], db)['seats']}:
            raise AppError('座位号无效')

    def export_data(self,db,ids):
        marks=','.join('?' for _ in ids)
        result={'rounds':[dict(r) for r in db.execute('SELECT * FROM rounds WHERE class_id IN ('+marks+')',ids)]}
        for table in ('registrations','submissions'):
            result[table]=[dict(r) for r in db.execute('SELECT t.*,r.class_id FROM '+table+' t JOIN rounds r ON r.id=t.round_id WHERE r.class_id IN ('+marks+')',ids)]
        return result
