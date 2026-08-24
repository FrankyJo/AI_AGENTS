"""
JSON-сховище прогресу, один файл на користувача (за chat_id з Telegram).
Просте персональне використання — файлового блокування немає навмисно.
"""

import copy
import json
import pathlib

DATA_DIR = pathlib.Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)

DEFAULT = {
    "profile": {"goals": "", "level": "", "equipment": [], "constraints": []},
    "program": {"name": "", "days": []},
    "history": [],
}


def _path(chat_id: str) -> pathlib.Path:
    return DATA_DIR / f"{chat_id}.json"


def load(chat_id: str) -> dict:
    p = _path(chat_id)
    if not p.exists():
        return copy.deepcopy(DEFAULT)
    return json.loads(p.read_text(encoding="utf-8"))


def save(chat_id: str, data: dict) -> None:
    _path(chat_id).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def delete(chat_id: str) -> None:
    p = _path(chat_id)
    if p.exists():
        p.unlink()
