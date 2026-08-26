"""
Розрахунок вартості прогону.

Ціни — за мільйон токенів, станом на 2026-08. Правити тут, якщо змінились.

Prompt caching (Anthropic): запис у кеш ("cache_write") коштує дорожче за
звичайний input (нова, ще не кешована частина запиту), а читання з кешу
("cache_read", коли system+tools збіглися з попереднім запитом) — набагато
дешевше. Множники стандартні для всіх моделей Claude.
"""

PRICES = {
    "claude-sonnet-4-6": {"in": 3.00, "out": 15.00},
    "claude-haiku-4-5-20251001": {"in": 1.00, "out": 5.00},
}

CACHE_WRITE_MULTIPLIER = 1.25
CACHE_READ_MULTIPLIER = 0.1


def _cost_for(u: dict, p: dict) -> float:
    return (u.get("in", 0) / 1e6 * p["in"]
            + u.get("out", 0) / 1e6 * p["out"]
            + u.get("cache_write", 0) / 1e6 * p["in"] * CACHE_WRITE_MULTIPLIER
            + u.get("cache_read", 0) / 1e6 * p["in"] * CACHE_READ_MULTIPLIER)


def usd(by_model: dict) -> float:
    total = 0.0
    for model, u in by_model.items():
        p = PRICES.get(model)
        if not p:
            continue
        total += _cost_for(u, p)
    return round(total, 6)


def aggregate(records: list) -> dict:
    """Сумує by_model з кількох записів usage_log (кожен — {"by_model": {...}})
    в один by_model-словник, придатний для usd()/breakdown()."""
    total = {}
    for r in records:
        for model, u in r["by_model"].items():
            m = total.setdefault(model, {"calls": 0, "in": 0, "out": 0, "cache_write": 0, "cache_read": 0})
            m["calls"] += u.get("calls", 0)
            m["in"] += u.get("in", 0)
            m["out"] += u.get("out", 0)
            m["cache_write"] += u.get("cache_write", 0)
            m["cache_read"] += u.get("cache_read", 0)
    return total


def breakdown(by_model: dict) -> list:
    rows = []
    for model, u in by_model.items():
        p = PRICES.get(model, {"in": 0, "out": 0})
        c = _cost_for(u, p)
        rows.append({"model": model, "calls": u.get("calls", 0),
                     "in": u.get("in", 0), "out": u.get("out", 0),
                     "cache_write": u.get("cache_write", 0), "cache_read": u.get("cache_read", 0),
                     "usd": round(c, 6)})
    return sorted(rows, key=lambda r: -r["usd"])
