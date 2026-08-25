"""
Обчислення похідної статистики прогресу з history: тоннаж за тренування,
прогресія ваги по вправі. Чисті функції без сторонніх ефектів (не читають
storage самі) — приймають уже завантажені дані, це спрощує тестування і
дозволяє однаково використовувати їх і з domain/backend.py, і з webapp/server.py.

weight/reps у history — вільний текст (як вводить користувач чи агент), тому
парсинг best-effort: що не розпізналось як число — просто не йде в підрахунок
обсягу, а не падає з помилкою (наприклад вправи з власною вагою тіла).
"""

import re

_NUM_RE = re.compile(r"\d+(?:[.,]\d+)?")


def parse_number(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = _NUM_RE.search(str(value))
    return float(match.group().replace(",", ".")) if match else None


def normalize_sets(ex: dict) -> list:
    """Уніфікує дві форми запису вправи в history: подетальну (sets_detail з
    log_set/finish_exercise_set_log) і одним рядком (weight/reps з log_workout)."""
    if ex.get("sets_detail"):
        return ex["sets_detail"]
    if ex.get("weight") or ex.get("reps"):
        return [{"weight": ex.get("weight", ""), "reps": ex.get("reps", "")}]
    return []


def set_volume_kg(s: dict) -> float:
    weight = parse_number(s.get("weight"))
    reps = parse_number(s.get("reps"))
    if weight is None or reps is None:
        return 0.0
    return weight * reps


def workout_volume_kg(entry: dict) -> float:
    return sum(set_volume_kg(s) for ex in entry.get("exercises", []) for s in normalize_sets(ex))


def volume_series(history: list) -> list:
    """Тоннаж за кожне тренування в хронологічному порядку — для графіка прогресу."""
    return [{"date": entry["date"], "volume_kg": round(workout_volume_kg(entry), 1)}
            for entry in history]


def exercise_progression(history: list, exercise: str) -> list:
    """Для кожного разу, коли виконувалась ця вправа: дата, найважчий підхід
    (за вагою) і сумарний обсяг вправи того дня — для графіка прогресії ваги."""
    out = []
    for entry in history:
        for ex in entry.get("exercises", []):
            if ex.get("name") != exercise:
                continue
            sets = normalize_sets(ex)
            weights = [w for w in (parse_number(s.get("weight")) for s in sets) if w is not None]
            out.append({"date": entry["date"],
                        "top_weight_kg": max(weights) if weights else None,
                        "volume_kg": round(sum(set_volume_kg(s) for s in sets), 1)})
    return out
