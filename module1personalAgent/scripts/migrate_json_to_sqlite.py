"""
Одноразова міграція старих JSON-файлів storage/data/<chat_id>.json у
storage/data/app.db (SQLite) — після переходу storage/store.py на SQLite-бекенд.

Безпечно запускати повторно (просто перезапише ті самі записи). Файли-джерела
НЕ видаляє — прибери вручну після перевірки, що дані на місці.

    python scripts/migrate_json_to_sqlite.py
"""

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from storage import store

DATA_DIR = pathlib.Path(__file__).resolve().parent.parent / "storage" / "data"


def main() -> None:
    migrated = 0
    for path in sorted(DATA_DIR.glob("*.json")):
        chat_id = path.stem
        data = json.loads(path.read_text(encoding="utf-8"))
        store.save(chat_id, data)
        migrated += 1
        print(f"  {chat_id} -> OK")

    if not migrated:
        print("Файлів storage/data/*.json не знайдено — мігрувати нічого.")
        return
    print(f"\nМігровано {migrated} користувач(ів) у {store.DB_PATH}")


if __name__ == "__main__":
    main()
