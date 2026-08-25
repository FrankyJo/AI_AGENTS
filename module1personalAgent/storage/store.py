"""
Сховище прогресу — SQLite, один рядок на користувача (chat_id), значення —
той самий JSON-блоб, що й раніше зберігався окремим файлом. Свідомо НЕ
переписано на повноцінну реляційну схему: увесь код, що працює з
data = store.load(chat_id) як зі словником (domain/backend.py, webapp/server.py,
тести), лишається без змін — міняється лише те, ЯК сховище фізично записує
дані. Причина переходу з raw-файлів на SQLite — атомарність (файловий запис
міг побитися, якщо процес впаде посеред save()) і безпечна конкурентність при
кількох користувачах одночасно, без потреби піднімати окремий сервер БД.
"""

import copy
import json
import pathlib
import sqlite3

DATA_DIR = pathlib.Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "app.db"

DEFAULT = {
    "profile": {"name": "", "goals": "", "level": "", "equipment": [], "constraints": [],
                "body_metrics": {"weight_kg": None, "measurements": {}, "updated_at": None,
                                  "next_check_in": None}},
    "program": {"name": "", "type": "", "days": [], "updated_at": None},
    "history": [],
    "active_set_log": None,
    "conversation": [],
    "memory_notes": "",
}


def _init_db() -> None:
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE IF NOT EXISTS users (chat_id TEXT PRIMARY KEY, data TEXT NOT NULL)")
        conn.commit()
    finally:
        conn.close()


_init_db()


def load(chat_id: str) -> dict:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    try:
        row = conn.execute("SELECT data FROM users WHERE chat_id = ?", (chat_id,)).fetchone()
    finally:
        conn.close()
    return json.loads(row[0]) if row else copy.deepcopy(DEFAULT)


def save(chat_id: str, data: dict) -> None:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    try:
        with conn:
            conn.execute(
                "INSERT INTO users (chat_id, data) VALUES (?, ?) "
                "ON CONFLICT(chat_id) DO UPDATE SET data = excluded.data",
                (chat_id, json.dumps(data, ensure_ascii=False)))
    finally:
        conn.close()


def delete(chat_id: str) -> None:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    try:
        with conn:
            conn.execute("DELETE FROM users WHERE chat_id = ?", (chat_id,))
    finally:
        conn.close()


def list_chat_ids() -> list:
    """Усі chat_id, для яких є збережені дані — рядки таблиці users і є реєстром користувачів."""
    conn = sqlite3.connect(DB_PATH, timeout=10)
    try:
        rows = conn.execute("SELECT chat_id FROM users").fetchall()
    finally:
        conn.close()
    return [r[0] for r in rows]
