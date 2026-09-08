"""Fill a template's XML cells without rebuilding its workbook/styles/drawings.

No spreadsheet engine is required on the teacher machine. Untouched ZIP members
remain byte-for-byte identical after decompression, including other worksheets.
"""
from datetime import datetime
from html import escape
from io import BytesIO
import json
import re
import zipfile
import xml.etree.ElementTree as ET

from classroom.core.errors import AppError


NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def set_cell(xml, ref, value):
    pattern = re.compile(r'<c\b(?=[^>]*\br="' + re.escape(ref) + r'")[^>]*?(?:/>|>.*?</c>)', re.S)
    match = pattern.search(xml)
    style = re.search(r'\bs="(\d+)"', match.group(0).split(">", 1)[0]) if match else None
    attrs = f' r="{ref}"' + (f' s="{style.group(1)}"' if style else "")
    if type(value) is int:
        cell = f'<c{attrs}><v>{value}</v></c>'
    else:
        cell = f'<c{attrs} t="inlineStr"><is><t xml:space="preserve">{escape(value)}</t></is></c>'
    if match:
        return xml[:match.start()] + cell + xml[match.end():]
    row_no = re.search(r'\d+$', ref).group(0)
    row_pattern = re.compile(r'(<row\b(?=[^>]*\br="' + row_no + r'")[^>]*>)(.*?)(</row>)', re.S)
    row = row_pattern.search(xml)
    if not row:
        raise AppError(f"模板缺少第 {row_no} 行", 500, "template_invalid")
    def col_index(cell_ref):
        n = 0
        for c in re.match(r'[A-Z]+', cell_ref).group(0):
            n = n * 26 + ord(c) - 64
        return n
    body = row.group(2)
    insert_at = len(body)
    for existing in re.finditer(r'<c\b[^>]*\br="([A-Z]+\d+)"', body):
        if col_index(existing.group(1)) > col_index(ref):
            insert_at = existing.start()
            break
    body = body[:insert_at] + cell + body[insert_at:]
    return xml[:row.start()] + row.group(1) + body + row.group(3) + xml[row.end():]


class ExcelExportService:
    def __init__(self, seating, config_dir):
        self.seating, self.config_dir = seating, config_dir

    def export(self, class_id, round_id=None):
        data = self.seating.get_arrangement(class_id, round_id)
        if not data["round"]:
            raise AppError("该班尚未开始登记")
        directory = self.config_dir
        cfg = json.loads((directory / "excel-template.json").read_text(encoding="utf-8"))
        if cfg['layout_id'] != data['layout']['id'] and data['layout']['id'] == 'classroom-64-v1':
            directory = directory / 'templates' / 'classroom-64-v1'
            cfg = json.loads((directory / 'excel-template.json').read_text(encoding='utf-8'))
        if cfg["layout_id"] != data["layout"]["id"]:
            raise AppError("该历史布局需要对应的 Excel 模板配置", 409, "template_mismatch")
        mapping = cfg["seat_cells"]
        numbers = {str(s["number"]) for s in data["layout"]["seats"]}
        if set(mapping) != numbers or len(set(mapping.values())) != len(numbers):
            raise AppError("模板座位映射不完整或重复", 500, "template_invalid")
        names = {str(r["seat_no"]): r["name"] for r in data["registrations"]}
        path = (directory / cfg["file"]).resolve()
        if not path.is_relative_to(self.config_dir.resolve()):
            raise AppError("模板路径必须位于配置目录", 500)
        output = BytesIO()
        with zipfile.ZipFile(path) as original, zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as result:
            xml = original.read(cfg["sheet_path"]).decode("utf-8")
            tree = ET.fromstring(xml)
            for seat, ref in cfg["number_cells"].items():
                cell = tree.find(f'.//s:c[@r="{ref}"]/s:v', NS)
                if cell is None or cell.text != seat:
                    raise AppError("原模板座位号与配置不一致，请检查模板", 500, "template_invalid")
            for number, ref in mapping.items():
                xml = set_cell(xml, ref, names.get(number, ""))
            xml = set_cell(xml, cfg["class_cell"], data["class"]["name"] + "  小组座位表")
            xml = set_cell(xml, cfg["count_cell"], data["count"])
            ET.fromstring(xml)  # Do not return a malformed workbook.
            for info in original.infolist():
                result.writestr(info, xml.encode("utf-8") if info.filename == cfg["sheet_path"] else original.read(info.filename))
        output.seek(0)
        safe_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", data["class"]["name"]).rstrip(". ") or "班级"
        label = '当前座位' if data['is_current'] else '存档'
        name = f'{safe_name}_座位表_{label}{data["round"]["number"]}_{datetime.now():%Y%m%d-%H%M%S}.xlsx'
        return output, name
