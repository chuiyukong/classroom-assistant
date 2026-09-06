from datetime import datetime, timezone
import sqlite3
from uuid import uuid4

from classroom.core.errors import AppError, clean_text


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ClassService:
    def __init__(self, database):
        self.database = database

    def list(self):
        with self.database.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM classes ORDER BY created_at, rowid")]

    def create(self, name):
        name = clean_text(name, "班级名称", 40)
        item = {"id": uuid4().hex, "name": name, "created_at": timestamp()}
        try:
            with self.database.connect(write=True) as db:
                db.execute("INSERT INTO classes VALUES (:id, :name, :created_at)", item)
        except sqlite3.IntegrityError:
            raise AppError("已有同名班级，请直接选择", 409, "class_exists")
        return item
