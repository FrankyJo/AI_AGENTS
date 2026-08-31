"""
Перевірка повноти індексації — чи справді витягнувся весь документ, а не
частина. Працює ЛИШЕ з тим, що вже лежить у laws.db — жодних запитів до
сайту (щоб не зловити зайве навантаження на API за надто часті звернення,
як цей проєкт уже разок словив під час розробки, коли скрапив
zakon.rada.gov.ua напряму).

    python verify.py
"""

import re
import sqlite3

import db

_ROMAN = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}


def _roman_to_int(s: str) -> int:
    total, prev = 0, 0
    for ch in reversed(s):
        v = _ROMAN.get(ch, 0)
        total += -v if v < prev else v
        prev = max(prev, v)
    return total


def _gaps(numbers: list[int]) -> list[int]:
    if not numbers:
        return []
    full = set(range(min(numbers), max(numbers) + 1))
    return sorted(full - set(numbers))


def check_document(conn: sqlite3.Connection, document_id: str, structure: str) -> None:
    n = conn.execute("SELECT COUNT(*) FROM clauses WHERE document_id=?", (document_id,)).fetchone()[0]
    print(f"  клауз у SQLite: {n}")

    if structure in ("law", "code"):
        rows = conn.execute(
            "SELECT DISTINCT article FROM clauses WHERE document_id=? AND article IS NOT NULL",
            (document_id,)).fetchall()
        nums = sorted({int(m.group(1)) for r in rows
                       if (m := re.match(r"Стаття\s+(\d+)\s*\.", r["article"], re.IGNORECASE))})
        print(f"  унікальних статей: {len(nums)} (1..{max(nums) if nums else 0})")
        gaps = _gaps(nums)
        if gaps:
            print(f"  ⚠ ПРОПУСКИ в нумерації статей: {gaps}")
        else:
            print("  пропусків у нумерації статей немає")

    if structure in ("pdr", "code"):
        rows = conn.execute(
            "SELECT DISTINCT section FROM clauses WHERE document_id=? AND section IS NOT NULL",
            (document_id,)).fetchall()
        if structure == "pdr":
            nums = sorted({int(m.group(1)) for r in rows
                           if (m := re.match(r"(\d+)\.", r["section"]))})
        else:
            # джерело інколи мішає кирилицю й латину у "римських" цифрах
            # (напр. "VІ" = латинська V + кириличне І) — той самий фікс,
            # що в crawler.py
            cyr2lat = str.maketrans({"І": "I", "Х": "X", "С": "C", "М": "M"})
            nums = sorted({_roman_to_int(m.group(1).translate(cyr2lat)) for r in rows
                           if (m := re.match(r"Розділ\s+([IVXLCDMІХСМ]+)", r["section"], re.IGNORECASE))})
        label = "розділів"
        print(f"  унікальних {label}: {len(nums)} (1..{max(nums) if nums else 0})")
        gaps = _gaps(nums)
        if gaps:
            print(f"  ⚠ ПРОПУСКИ в нумерації розділів: {gaps}  ← перевір вручну, можливо помилка парсера")
        else:
            print(f"  пропусків у нумерації {label} немає")


def main() -> None:
    conn = db.get_conn()
    docs = db.all_documents(conn)
    if not docs:
        print("laws.db порожня — спершу:  python ingest.py")
        return

    for doc in docs:
        print(f"\n=== {doc['title']} ({doc['id']}) ===")
        print(f"  номер акта: {doc['act_number']}, статус-код: {doc['status_code']}, "
              f"прийнято: {doc['adopted_date']}, редакція від {doc['revision_date']}")
        check_document(conn, doc["id"], doc["structure"])


if __name__ == "__main__":
    main()
