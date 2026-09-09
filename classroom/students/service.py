"""Stable class-local identities and private teacher notes, independent of seats."""
import unicodedata
from uuid import uuid4

from classroom.classes.service import timestamp
from classroom.core.errors import AppError, clean_text


def name_key(name):
    return ''.join(unicodedata.normalize('NFKC', name).split()).casefold()


def clean_note(note):
    if not isinstance(note, str) or len(note) > 1000:
        raise AppError('备注须为 0—1000 个字符')
    if any((ord(c) < 32 and c not in '\n\r\t') or 0xD800 <= ord(c) <= 0xDFFF or ord(c) in (0xFFFE, 0xFFFF) for c in note):
        raise AppError('备注包含无效字符')
    return note.strip()


class StudentService:
    def __init__(self, database):
        self.database = database

    def list(self, class_id):
        with self.database.connect() as db:
            if not db.execute('SELECT 1 FROM classes WHERE id=?', (class_id,)).fetchone():
                raise AppError('班级不存在', 404)
            roles = self.roles(db)
            return [dict(dict(r),role=roles.get(r['id'],0)) for r in db.execute('SELECT * FROM students WHERE class_id=? ORDER BY name_key, created_at, id', (class_id,))]

    def update_note(self, student_id, note):
        note = clean_note(note)
        with self.database.connect(write=True) as db:
            if not db.execute('SELECT 1 FROM students WHERE id=?', (student_id,)).fetchone():
                raise AppError('学生记录不存在', 404)
            db.execute('UPDATE students SET note=?, updated_at=? WHERE id=?', (note, timestamp(), student_id))

    def create(self, class_id, name, note=''):
        name, note = clean_text(name, '姓名', 30), clean_note(note)
        with self.database.connect(write=True) as db:
            if not db.execute('SELECT 1 FROM classes WHERE id=?', (class_id,)).fetchone():
                raise AppError('班级不存在', 404)
            sid = self.resolve(db, class_id, name, force_new=True)
            db.execute('UPDATE students SET note=? WHERE id=?', (note, sid))
            return dict(db.execute('SELECT * FROM students WHERE id=?', (sid,)).fetchone())

    @staticmethod
    def resolve(db, class_id, name, *, student_id=None, force_new=False, current=None, student_submission=False):
        """Teacher explicitly chooses duplicate identities; students match only unambiguous names."""
        key = name_key(name)
        if student_id:
            if not isinstance(student_id, str):
                raise AppError('学生编号无效')
            chosen = db.execute('SELECT * FROM students WHERE id=? AND class_id=?', (student_id, class_id)).fetchone()
            if not chosen:
                raise AppError('学生记录不属于当前班级', 400)
        elif current and not force_new:
            chosen = db.execute('SELECT * FROM students WHERE id=?', (current,)).fetchone()
        elif not force_new:
            matches = db.execute('SELECT * FROM students WHERE class_id=? AND name_key=?', (class_id, key)).fetchall()
            if len(matches) > 1:
                raise AppError('存在同名学生，请到教师端选择学生记录后登记', 409, 'duplicate_name')
            chosen = matches[0] if matches else None
        else:
            chosen = None
        if chosen:
            sid = chosen['id']
            if not student_submission:
                db.execute('UPDATE students SET name=?, name_key=?, updated_at=? WHERE id=?', (name, key, timestamp(), sid))
            return sid
        sid = uuid4().hex
        db.execute('INSERT INTO students VALUES (?, ?, ?, ?, ?, ?, ?)', (sid, class_id, name, key, '', timestamp(), timestamp()))
        return sid

    @staticmethod
    def roles(db):
        return {r['student_id']:r['role'] for r in db.execute('SELECT student_id,role FROM student_roles')}

    @staticmethod
    def set_role(db, student_id, role):
        if type(role) is not int or role not in range(4):
            raise AppError('学生职务标记无效')
        db.execute('INSERT INTO student_roles(student_id,role) VALUES (?,?) ON CONFLICT(student_id) DO UPDATE SET role=excluded.role', (student_id,role))

    def export_data(self,db,ids):
        marks=','.join('?' for _ in ids)
        roles = self.roles(db)
        return {'students':[dict(dict(r),role=roles.get(r['id'],0)) for r in db.execute('SELECT * FROM students WHERE class_id IN ('+marks+')',ids)]}
