"""DiaRepair 本地设置：持久化用户选择（如备份根目录）。"""

import json
import os


def settings_path() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    directory = os.path.join(base, "DiaRepair")
    os.makedirs(directory, exist_ok=True)
    return os.path.join(directory, "settings.json")


def load_settings(path: str = "") -> dict:
    path = path or settings_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_settings(data: dict, path: str = "") -> None:
    path = path or settings_path()
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
