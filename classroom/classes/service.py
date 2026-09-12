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
            return [dict(row) for row in db.execute("SELECT * FROM classes WHERE (deleted_at IS NOT NULL)=? ORDER BY year DESC, semester DESC, name, created_at", (deleted,))]

    def create(self, name, year=0, semester="", grade="", graduation_year=0):
        if type(year) is not int or (year != 0 and not 2000 <= year <= 2100) or semester not in ("", "上学期", "下学期") or bool(year) != bool(semester):
            raise AppError("请选择年份和上/下学期，或同时留空")
        self.validate_graduation(graduation_year)
        name = clean_text(name, "班级名称", 40)
        if not isinstance(grade, str) or len(grade.strip()) > 20:
            raise AppError("年级最多 20 个字")
        grade = grade.strip()
        item = {"id": uuid4().hex, "name": name, "created_at": timestamp(), "year": year, "semester": semester, "grade": grade, "graduation_year": graduation_year}
        try:
            with self.database.connect(write=True) as db:
                db.execute("INSERT INTO classes(id,name,created_at,year,semester,grade,graduation_year) VALUES (:id, :name, :created_at, :year, :semester, :grade, :graduation_year)", item)
        except sqlite3.IntegrityError:
            raise AppError("该年份学期已有同名班级，请选择已有班级或从回收站恢复", 409, "class_exists")
        return item

    def set_deleted(self, db, ids, deleted):
        if not isinstance(ids, list) or not ids or len(ids) > 500 or any(not isinstance(i, str) for i in ids):
            raise AppError('请选择需要管理的班级')
        for cid in set(ids):
            if not db.execute('SELECT 1 FROM classes WHERE id=?', (cid,)).fetchone():
                raise AppError('班级不存在', 404)
            db.execute('UPDATE classes SET deleted_at=? WHERE id=?', (timestamp() if deleted else None, cid))

    def rename(self,cid,name,graduation_year):
        name=clean_text(name,'班级名称',40)
        self.validate_graduation(graduation_year)
        try:
            with self.database.connect(write=True) as db:
                if not db.execute('SELECT 1 FROM classes WHERE id=?',(cid,)).fetchone():raise AppError('班级不存在',404)
                db.execute('UPDATE classes SET name=?,graduation_year=? WHERE id=?',(name,graduation_year,cid))
        except sqlite3.IntegrityError:
            raise AppError('该届该学期已有同名班级',409)

    def set_grade(self, cid, grade):
        if not isinstance(grade, str) or len(grade.strip()) > 20:
            raise AppError('年级最多 20 个字')
        with self.database.connect(write=True) as db:
            if not db.execute('SELECT 1 FROM classes WHERE id=?', (cid,)).fetchone():
                raise AppError('班级不存在',404)
            db.execute('UPDATE classes SET grade=? WHERE id=?',(grade.strip(),cid))

    @staticmethod
    def validate_graduation(value):
        if type(value) is not int or (value!=0 and not 1900<=value<=2200):
            raise AppError('毕业届数请填写四位年份，例如2029；未设置可留空')

    def set_graduation(self,cid,value):
        self.validate_graduation(value)
        try:
            with self.database.connect(write=True) as db:
                if not db.execute('SELECT 1 FROM classes WHERE id=?',(cid,)).fetchone():
                    raise AppError('班级不存在',404)
                db.execute('UPDATE classes SET graduation_year=? WHERE id=?',(value,cid))
        except sqlite3.IntegrityError:
            raise AppError('该届该学期已有同名班级',409)

    def export_data(self,db,ids):
        marks=','.join('?' for _ in ids)
        rows=[dict(r) for r in db.execute('SELECT * FROM classes WHERE id IN ('+marks+')',ids)]
        if len(rows)!=len(ids):
            raise AppError('选中的班级不存在',404)
        return {'classes':rows}
