from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
import sqlite3


MIGRATIONS = [(1, """
CREATE TABLE classes (
 id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL
);
CREATE TABLE layouts (
 id TEXT PRIMARY KEY, definition TEXT NOT NULL
);
CREATE TABLE rounds (
 id TEXT PRIMARY KEY, class_id TEXT NOT NULL REFERENCES classes(id),
 layout_id TEXT NOT NULL REFERENCES layouts(id), number INTEGER NOT NULL,
 opened_at TEXT NOT NULL, closed_at TEXT, is_open INTEGER NOT NULL DEFAULT 1,
 UNIQUE(class_id, number)
);
CREATE UNIQUE INDEX one_open_round ON rounds(is_open) WHERE is_open = 1;
CREATE TABLE registrations (
 id TEXT PRIMARY KEY, round_id TEXT NOT NULL REFERENCES rounds(id),
 seat_no INTEGER NOT NULL, name TEXT NOT NULL, client_id TEXT,
 updated_at TEXT NOT NULL, UNIQUE(round_id, seat_no), UNIQUE(round_id, client_id)
);
CREATE TABLE submissions (
 round_id TEXT NOT NULL REFERENCES rounds(id), client_id TEXT NOT NULL,
 request_id TEXT NOT NULL, seat_no INTEGER NOT NULL, name TEXT NOT NULL,
 registration_id TEXT NOT NULL,
 PRIMARY KEY(round_id, client_id, request_id)
);
CREATE INDEX rounds_class ON rounds(class_id, number DESC);
"""), (2, """
ALTER TABLE registrations ADD COLUMN source_ip TEXT;
ALTER TABLE registrations ADD COLUMN ip_key TEXT;
ALTER TABLE registrations ADD COLUMN student_id TEXT REFERENCES students(id);
ALTER TABLE registrations ADD COLUMN student_note TEXT NOT NULL DEFAULT '';
ALTER TABLE rounds ADD COLUMN archived_at TEXT;
CREATE TABLE students (
 id TEXT PRIMARY KEY, class_id TEXT NOT NULL REFERENCES classes(id),
 name TEXT NOT NULL, name_key TEXT NOT NULL, note TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX students_class_name ON students(class_id, name_key);
CREATE TABLE seat_configs (
 layout_id TEXT NOT NULL REFERENCES layouts(id), seat_no INTEGER NOT NULL,
 disabled INTEGER NOT NULL DEFAULT 0 CHECK(disabled IN (0,1)),
 note TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL,
 PRIMARY KEY(layout_id, seat_no)
);
CREATE TABLE classroom_state (
 singleton INTEGER PRIMARY KEY CHECK(singleton=1),
 active_class_id TEXT REFERENCES classes(id)
);
INSERT INTO classroom_state VALUES (1, (
 SELECT class_id FROM rounds ORDER BY is_open DESC, rowid DESC LIMIT 1
));
UPDATE rounds SET archived_at=COALESCE(closed_at, opened_at)
 WHERE number < (SELECT MAX(r.number) FROM rounds r WHERE r.class_id=rounds.class_id);
-- Never guess that old same-name registrations are the same person.
-- Give every old record an independent identity; current identities are reused
-- by later registration. The Python migration below assigns normalized keys.
INSERT INTO students(id, class_id, name, name_key, note, created_at, updated_at)
 SELECT g.id, r.class_id, g.name, g.name, '', g.updated_at, g.updated_at
 FROM registrations g JOIN rounds r ON r.id=g.round_id
 WHERE r.archived_at IS NULL;
UPDATE registrations SET student_id=id WHERE id IN (SELECT id FROM students);
CREATE UNIQUE INDEX registration_ip ON registrations(round_id, ip_key) WHERE ip_key IS NOT NULL;
CREATE UNIQUE INDEX registration_student ON registrations(round_id, student_id) WHERE student_id IS NOT NULL;
""")]


MIGRATIONS.append((3, """
ALTER TABLE classes ADD COLUMN deleted_at TEXT;
CREATE TABLE lessons (
 id TEXT PRIMARY KEY, class_id TEXT NOT NULL REFERENCES classes(id), round_id TEXT NOT NULL,
 class_name TEXT NOT NULL, started_at TEXT NOT NULL, ended_at TEXT,
 attendance_started_at TEXT, attendance_closed_at TEXT, late_after INTEGER NOT NULL DEFAULT 5
);
CREATE UNIQUE INDEX one_live_lesson ON lessons((1)) WHERE ended_at IS NULL;
CREATE TABLE attendance_entries (
 lesson_id TEXT NOT NULL REFERENCES lessons(id), student_id TEXT NOT NULL,
 name TEXT NOT NULL, original_seat INTEGER NOT NULL, seat_no INTEGER,
 status TEXT NOT NULL DEFAULT 'pending', signed_at TEXT, late_seconds INTEGER NOT NULL DEFAULT 0,
 source_ip TEXT, client_id TEXT, PRIMARY KEY(lesson_id, student_id),
 UNIQUE(lesson_id, seat_no), UNIQUE(lesson_id, source_ip), UNIQUE(lesson_id, client_id)
);
CREATE TABLE attendance_leave (student_id TEXT PRIMARY KEY, class_id TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE rollcall_draws (
 id TEXT PRIMARY KEY, lesson_id TEXT NOT NULL REFERENCES lessons(id), student_id TEXT NOT NULL,
 name TEXT NOT NULL, seat_no INTEGER NOT NULL, source TEXT NOT NULL, created_at TEXT NOT NULL
);
"""))


MIGRATIONS.append((4, """
ALTER TABLE lessons ADD COLUMN attendance_deadline TEXT;
ALTER TABLE lessons ADD COLUMN layout_id TEXT;
UPDATE lessons SET layout_id=(SELECT layout_id FROM rounds WHERE rounds.id=lessons.round_id);
ALTER TABLE attendance_entries ADD COLUMN move_reason TEXT NOT NULL DEFAULT '';
CREATE TABLE seat_change_requests (
 id TEXT PRIMARY KEY, lesson_id TEXT NOT NULL REFERENCES lessons(id),
 student_id TEXT NOT NULL, from_seat INTEGER NOT NULL, to_seat INTEGER NOT NULL,
 status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL, decided_at TEXT,
 UNIQUE(lesson_id, student_id)
);
"""))


MIGRATIONS.append((5, """
CREATE TABLE classes_new (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL,
 deleted_at TEXT, year INTEGER NOT NULL DEFAULT 0, semester TEXT NOT NULL DEFAULT '',
 UNIQUE(name, year, semester)
);
INSERT INTO classes_new(id,name,created_at,deleted_at) SELECT id,name,created_at,deleted_at FROM classes;
DROP TABLE classes;
ALTER TABLE classes_new RENAME TO classes;
"""))


MIGRATIONS.append((6, """
ALTER TABLE classes ADD COLUMN grade TEXT NOT NULL DEFAULT '';
ALTER TABLE lessons ADD COLUMN grade TEXT NOT NULL DEFAULT '';
ALTER TABLE lessons ADD COLUMN year INTEGER NOT NULL DEFAULT 0;
ALTER TABLE lessons ADD COLUMN semester TEXT NOT NULL DEFAULT '';
UPDATE lessons SET grade=COALESCE((SELECT grade FROM classes WHERE classes.id=lessons.class_id),''),
 year=COALESCE((SELECT year FROM classes WHERE classes.id=lessons.class_id),0),
 semester=COALESCE((SELECT semester FROM classes WHERE classes.id=lessons.class_id),'');
ALTER TABLE attendance_entries ADD COLUMN first_signed_at TEXT;
UPDATE attendance_entries SET first_signed_at=signed_at;
ALTER TABLE attendance_entries ADD COLUMN recheckin_allowed INTEGER NOT NULL DEFAULT 0;
ALTER TABLE seat_change_requests ADD COLUMN kind TEXT NOT NULL DEFAULT 'long_term';
CREATE TABLE attendance_events (
 id TEXT PRIMARY KEY, lesson_id TEXT NOT NULL REFERENCES lessons(id), student_id TEXT NOT NULL,
 action TEXT NOT NULL, seat_no INTEGER, source_ip TEXT, created_at TEXT NOT NULL
);
CREATE TABLE rollcall_selections (
 class_id TEXT PRIMARY KEY REFERENCES classes(id), student_ids TEXT NOT NULL, updated_at TEXT NOT NULL
);
"""))


MIGRATIONS.append((7, """
CREATE TABLE classes_v7 (
 id TEXT PRIMARY KEY,name TEXT NOT NULL,created_at TEXT NOT NULL,deleted_at TEXT,
 year INTEGER NOT NULL DEFAULT 0,semester TEXT NOT NULL DEFAULT '',grade TEXT NOT NULL DEFAULT '',
 graduation_year INTEGER NOT NULL DEFAULT 0,
 UNIQUE(name,year,semester,graduation_year)
);
INSERT INTO classes_v7(id,name,created_at,deleted_at,year,semester,grade)
 SELECT id,name,created_at,deleted_at,year,semester,grade FROM classes;
DROP TABLE classes;
ALTER TABLE classes_v7 RENAME TO classes;
ALTER TABLE lessons ADD COLUMN graduation_year INTEGER NOT NULL DEFAULT 0;
"""))


MIGRATIONS.append((8, """
CREATE TABLE student_roles (student_id TEXT PRIMARY KEY REFERENCES students(id), role INTEGER NOT NULL DEFAULT 0 CHECK(role BETWEEN 0 AND 3));
ALTER TABLE registrations ADD COLUMN role INTEGER NOT NULL DEFAULT 0;
ALTER TABLE attendance_entries ADD COLUMN role INTEGER NOT NULL DEFAULT 0;
"""))

class Database:
    def __init__(self, path):
        self.path = Path(path)
        self.diagnostics = None

    @contextmanager
    def connect(self, write=False):
        import time
        start = time.monotonic()
        db = None
        begun = start
        error = None
        try:
            db = sqlite3.connect(self.path, timeout=15, isolation_level=None)
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA busy_timeout=15000")
            db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            begun = time.monotonic()
            yield db
            db.commit()
        except Exception as exc:
            error = exc
            if begun == start:begun = time.monotonic()
            if db is not None:db.rollback()
            raise
        finally:
            if db is not None:db.close()
            if self.diagnostics:
                self.diagnostics.db_event(write, (begun-start)*1000, (time.monotonic()-begun)*1000, error)

    def migrate(self, skip_backup_for_version=None):
        with sqlite3.connect(self.path) as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version > MIGRATIONS[-1][0]:
                raise RuntimeError("数据库版本比程序新，请使用新版程序")
            if version < MIGRATIONS[-1][0] and self.path.stat().st_size and skip_backup_for_version != MIGRATIONS[-1][0]:
                backup_dir = self.path.parent / "backups"
                backup_dir.mkdir(exist_ok=True)
                stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
                with sqlite3.connect(backup_dir / f"before-v{version + 1}-{stamp}.sqlite3") as copy:
                    db.backup(copy)
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=FULL")
            for number, sql in MIGRATIONS:
                if number > version:
                    try:
                        db.executescript(f"BEGIN IMMEDIATE;\n{sql}")
                        if number == 2:
                            from classroom.students.service import name_key
                            for sid, name in db.execute("SELECT id, name FROM students").fetchall():
                                db.execute("UPDATE students SET name_key=? WHERE id=?", (name_key(name), sid))
                        db.execute(f"PRAGMA user_version={number}")
                        db.commit()
                    except Exception:
                        db.rollback()
                        raise
