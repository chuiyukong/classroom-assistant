import sqlite3

import pytest

from classroom.core.db import Database


def test_upgrade_backup_and_newer_version_rejected(tmp_path):
    path = tmp_path / 'data.sqlite3'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE previous_data (value TEXT)')
        db.execute("INSERT INTO previous_data VALUES ('retained')")
    Database(path).migrate()
    copies = list((tmp_path / 'backups').glob('*.sqlite3'))
    assert len(copies) == 1
    with sqlite3.connect(copies[0]) as db:
        assert db.execute('SELECT value FROM previous_data').fetchone()[0] == 'retained'
        assert db.execute('PRAGMA user_version').fetchone()[0] == 0
    with sqlite3.connect(path) as db:
        db.execute('PRAGMA user_version=999')
    with pytest.raises(RuntimeError, match='数据库版本比程序新'):
        Database(path).migrate()
