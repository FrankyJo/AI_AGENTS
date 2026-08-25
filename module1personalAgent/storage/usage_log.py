"""
Лог витрат API — один JSONL-файл, один рядок на кожен завершений прогін
run_agent. Не має власного chat_id-скоупу, як storage/store.py: оплата йде з
одного API-ключа незалежно від того, з якого чату прийшов запит, тому /usage
рахує сумарну вартість по всьому боту.
"""

import datetime
import json
import pathlib

LOG_PATH = pathlib.Path(__file__).parent / "data" / "usage_log.jsonl"


def append(chat_id: str, by_model: dict, path: pathlib.Path = None) -> None:
    if not by_model:                             # прогін без жодного виклику API — нема що логувати
        return
    path = path or LOG_PATH
    path.parent.mkdir(exist_ok=True)
    record = {"ts": datetime.datetime.now().isoformat(timespec="seconds"),
              "chat_id": str(chat_id), "by_model": by_model}
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_all(path: pathlib.Path = None) -> list:
    path = path or LOG_PATH
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def for_chat(chat_id: str, path: pathlib.Path = None) -> list:
    """Записи лише одного чату — щоб кожен користувач бачив саме свої витрати,
    а не сумарні по всьому боту (потрібно, якщо ботом користується кілька людей
    і кожен покриває свою частину рахунку)."""
    chat_id = str(chat_id)
    return [r for r in read_all(path=path) if r["chat_id"] == chat_id]
