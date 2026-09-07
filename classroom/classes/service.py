from datetime import datetime, timezone
import sqlite3
from uuid import uuid4

from classroom.core.errors import AppError, clean_text


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ClassService:
    def __init__(self, database):
        self.database = database

    def list(self, deleted=False):
        with self.database.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM classes WHERE (deleted_at IS NOT NULL)=? ORDER BY created_at, rowid", (deleted,))]

    def create(self, name):
        name = clean_text(name, "班级名称", 40)
        item = {"id": uuid4().hex, "name": name, "created_at": timestamp()}
        try:
            with self.database.connect(write=True) as db:
                db.execute("INSERT INTO classes(id,name,created_at) VALUES (:id, :name, :created_at)", item)
        except sqlite3.IntegrityError:
            raise AppError("已有同名班级，请直接选择；如在回收站中请先恢复，或给新学期班级添加学期前缀", 409, "class_exists")
        return item

    def set_deleted(self, db, ids, deleted):
        if not isinstance(ids, list) or not ids or len(ids) > 500 or any(not isinstance(i, str) for i in ids):
            raise AppError('请选择需要管理的班级')
        for cid in set(ids):
            if not db.execute('SELECT 1 FROM classes WHERE id=?', (cid,)).fetchone():
                raise AppError('班级不存在', 404)
            db.execute('UPDATE classes SET deleted_at=? WHERE id=?', (timestamp() if deleted else None, cid))
