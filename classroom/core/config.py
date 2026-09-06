import json
import os
from pathlib import Path
import secrets
import shutil
import sys


def resource_dir():
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2])) / "resources"


def prepare_data(data_dir=None):
    root = Path(data_dir or os.environ.get("CLASSROOM_DATA_DIR") or
                Path(os.environ.get("LOCALAPPDATA", Path.home())) / "ClassroomAssistant")
    root.mkdir(parents=True, exist_ok=True)
    config = root / "config"
    config.mkdir(exist_ok=True)
    for name in ("layout.json", "excel-template.json", "seat-template.xlsx"):
        target = config / name
        if not target.exists():
            shutil.copyfile(resource_dir() / name, target)
    secret = root / "session.key"
    if not secret.exists():
        secret.write_text(secrets.token_hex(32), encoding="ascii")
    settings_file = root / "settings.json"
    if not settings_file.exists():
        settings_file.write_text(json.dumps({"port": 8765, "limit_one_registration_per_ip": True}, indent=2), encoding="utf-8")
    settings = json.loads(settings_file.read_text(encoding="utf-8"))
    port = settings.get("port", 8765)
    if type(port) is not int or not 1024 <= port <= 65535:
        raise ValueError("settings.json 中 port 须为 1024—65535 的整数")
    return root, secret.read_text(encoding="ascii"), port
