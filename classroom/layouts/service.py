import json


class LayoutService:
    def __init__(self, database, config_dir):
        self.database = database
        self.current = json.loads((config_dir / "layout.json").read_text(encoding="utf-8"))
        seats = self.current["seats"]
        numbers = [s["number"] for s in seats]
        if len(set(numbers)) != len(numbers) or not numbers or any(type(n) is not int for n in numbers):
            raise ValueError("教室布局座位号必须是互不重复的整数")
        definition = json.dumps(self.current, ensure_ascii=False, sort_keys=True)
        with database.connect(write=True) as db:
            row = db.execute("SELECT definition FROM layouts WHERE id=?", (self.current["id"],)).fetchone()
            if row and row[0] != definition:
                raise ValueError("布局内容已变更，请同时修改 layout.json 的 id，以保留历史布局")
            db.execute("INSERT OR IGNORE INTO layouts VALUES (?, ?)", (self.current["id"], definition))
            if not row and self.current['id'] == 'classroom-64-v2':
                db.execute('''INSERT OR IGNORE INTO seat_configs SELECT ?,seat_no,disabled,note,updated_at
                    FROM seat_configs WHERE layout_id='classroom-64-v1' ''', (self.current['id'],))

    def get(self, layout_id, connection):
        row = connection.execute("SELECT definition FROM layouts WHERE id=?", (layout_id,)).fetchone()
        return json.loads(row[0])
