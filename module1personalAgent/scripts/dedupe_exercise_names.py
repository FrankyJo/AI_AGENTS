"""
Знаходить вправи в program/history користувача, назви яких — це той самий
рух, записаний різними мовами чи словами (найчастіша причина — модель
переклала чи перефразувала вже збережену назву під мову повідомлення
користувача, напр. «Горизонтальна тяга» і «Горизонтальная тяга»), і зводить
їх до однієї назви.

Порівнює назви ОДНА З ОДНОЮ (не з каталогом exercises-dataset — там зовсім
інша, машинно перекладена номенклатура з 1324 вправ, і мапити прості
історичні назви на неї тільки погіршило б читабельність). Кластеризує схожі
рядки (SequenceMatcher ratio), у кожному кластері обирає канонічну форму:
перевага — точний збіг з каталогом exercises-dataset, якщо є; інакше — форма,
що вперше з'явилась в history (оригінал, а не пізніше перефразування);
інакше — найчастіша.

За замовчуванням — dry-run, нічого не зберігає, тільки показує план замін.

    python scripts/dedupe_exercise_names.py <chat_id>              # dry-run
    python scripts/dedupe_exercise_names.py <chat_id> --apply      # застосувати
"""

import argparse
import collections
import difflib
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from domain.exercises import EXERCISES
from storage import store

CATALOG_NAMES = set(e["name"] for e in EXERCISES)
SIMILARITY_THRESHOLD = 0.75


def cluster_names(names: list) -> list:
    """Групує схожі назви разом (union-find на порозі схожості)."""
    names = sorted(names)
    parent = {n: n for n in names}

    def find(n):
        while parent[n] != n:
            parent[n] = parent[parent[n]]
            n = parent[n]
        return n

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for i, a in enumerate(names):
        for b in names[i + 1:]:
            if difflib.SequenceMatcher(None, a, b).ratio() >= SIMILARITY_THRESHOLD:
                union(a, b)

    groups = collections.defaultdict(list)
    for n in names:
        groups[find(n)].append(n)
    return [g for g in groups.values() if len(g) > 1]


def collect_first_seen(data: dict) -> dict:
    """Для кожної назви — найраніша дата, коли вона з'явилась в history."""
    first_seen = {}
    for entry in data["history"]:
        date = entry.get("date", "")
        for ex in entry.get("exercises", []):
            name = ex["name"]
            if name not in first_seen or date < first_seen[name]:
                first_seen[name] = date
    return first_seen


def pick_canonical(group: list, counts: collections.Counter, first_seen: dict) -> str:
    """Канонічна форма — та, що з'явилась в history РАНІШЕ за інші (оригінал,
    а не пізніше перефразування/переклад). Якщо жодна з форм не залогована в
    history (лише в program) — найчастіша, тоді алфавітно перша."""
    catalog_hit = [n for n in group if n in CATALOG_NAMES]
    if catalog_hit:
        return catalog_hit[0]
    dated = [n for n in group if n in first_seen]
    if dated:
        return min(dated, key=lambda n: (first_seen[n], -counts[n], n))
    return max(group, key=lambda n: (counts[n], n))


def collect_name_counts(data: dict) -> collections.Counter:
    counts = collections.Counter()
    for day in data["program"].get("days", []):
        for ex in day.get("exercises", []):
            counts[ex["name"]] += 1
    for entry in data["history"]:
        for ex in entry.get("exercises", []):
            counts[ex["name"]] += 1
    return counts


def apply_rename(data: dict, rename_map: dict) -> int:
    renamed = 0
    for day in data["program"].get("days", []):
        for ex in day.get("exercises", []):
            if ex["name"] in rename_map:
                ex["name"] = rename_map[ex["name"]]
                renamed += 1
        # після перейменування могли з'явитись дублі в межах одного дня — приберемо
        seen = set()
        deduped = []
        for ex in day["exercises"]:
            if ex["name"] in seen:
                continue
            seen.add(ex["name"])
            deduped.append(ex)
        day["exercises"] = deduped

    for entry in data["history"]:
        for ex in entry.get("exercises", []):
            if ex["name"] in rename_map:
                ex["name"] = rename_map[ex["name"]]
                renamed += 1
    return renamed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("chat_id")
    parser.add_argument("--apply", action="store_true",
                         help="Реально зберегти зміни (без цього — тільки показ плану)")
    args = parser.parse_args()

    data = store.load(args.chat_id)
    counts = collect_name_counts(data)
    first_seen = collect_first_seen(data)
    groups = cluster_names(list(counts.keys()))

    rename_map = {}
    for group in groups:
        canonical = pick_canonical(group, counts, first_seen)
        for name in group:
            if name != canonical:
                rename_map[name] = canonical

    if not rename_map:
        print("Дублів (схожих назв) не знайдено.")
        return

    print("Пропоновані заміни:")
    for old, new in rename_map.items():
        print(f"  {old!r} -> {new!r}")

    if args.apply:
        n = apply_rename(data, rename_map)
        store.save(args.chat_id, data)
        print(f"\nЗастосовано. Перейменовано {n} входжень.")
    else:
        print("\nЦе dry-run, нічого не збережено. Додай --apply, щоб застосувати.")


if __name__ == "__main__":
    main()
