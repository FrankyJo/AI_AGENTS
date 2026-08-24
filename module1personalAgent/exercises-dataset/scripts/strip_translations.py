#!/usr/bin/env python3
"""
Скрипт видаляє всі мовні переклади, крім "uk", у полях
"instructions" та "instruction_steps" файлу exercises.json.

Використання:
    python3 strip_translations.py [шлях_до_json]

Якщо шлях не вказано, використовується стандартний шлях
../data/exercises.json відносно розташування скрипта.
Перед перезаписом створюється резервна копія *.bak.json.
"""

import json
import sys
from pathlib import Path

KEEP_LANG = "uk"
FIELDS_TO_CLEAN = ("instructions", "instruction_steps")


def strip_translations(data: list[dict]) -> int:
    """Видаляє всі мови, крім KEEP_LANG, у FIELDS_TO_CLEAN. Повертає кількість змінених записів."""
    changed = 0
    for item in data:
        item_changed = False
        for field in FIELDS_TO_CLEAN:
            value = item.get(field)
            if isinstance(value, dict):
                removed_keys = [lang for lang in value if lang != KEEP_LANG]
                if removed_keys:
                    for lang in removed_keys:
                        del value[lang]
                    item_changed = True
        if item_changed:
            changed += 1
    return changed


def main():
    default_path = Path(__file__).resolve().parent.parent / "data" / "exercises.json"
    json_path = Path(sys.argv[1]) if len(sys.argv) > 1 else default_path

    if not json_path.exists():
        print(f"Файл не знайдено: {json_path}")
        sys.exit(1)

    with json_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        print("Очікувався JSON-масив на верхньому рівні.")
        sys.exit(1)

    backup_path = json_path.with_suffix(".bak.json")
    with backup_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"Резервну копію збережено: {backup_path}")

    changed = strip_translations(data)

    with json_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(f"Оброблено записів зі змінами: {changed} із {len(data)}")
    print(f"Файл оновлено: {json_path}")


if __name__ == "__main__":
    main()
