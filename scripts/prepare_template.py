"""One-time, explicit developer utility: derive resources from the supplied template."""
from pathlib import Path
import json
import shutil

ROOT = Path(__file__).resolve().parents[1]
output = ROOT / "resources"
output.mkdir(exist_ok=True)
rows = [5, 6, 8, 9, 10, 12, 13, 14]
number_cols = ["C", "E", "I", "K", "O", "Q", "U", "W"]
name_cols = ["D", "F", "J", "L", "P", "R", "V", "X"]
group_names = ["一组", "二组", "三组", "四组", "五组", "六组", "七组", "八组", "九组", "十组", "十一", "十二"]
seats, number_cells, seat_cells = [], {}, {}
for col in range(8):
    for row in range(8):
        number = col * 8 + 8 - row
        group_index = (col // 2) * 3 + (2 if row < 2 else 1 if row < 5 else 0)
        seats.append({"number": number, "big_group": col // 2 + 1, "group": group_names[group_index], "row": row, "column": col % 2})
        number_cells[str(number)] = number_cols[col] + str(rows[row])
        seat_cells[str(number)] = name_cols[col] + str(rows[row])
layout = {"id": "classroom-64-v1", "name": "计算机教室", "podium": "bottom", "seats": seats}
template = {"layout_id": layout["id"], "file": "seat-template.xlsx", "sheet_path": "xl/worksheets/sheet1.xml", "class_cell": "C3", "count_cell": "E17", "seat_cells": seat_cells, "number_cells": number_cells}
for name, value in (("layout.json", layout), ("excel-template.json", template)):
    (output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
shutil.copyfile(ROOT / "分组座位表.xlsx", output / "seat-template.xlsx")
