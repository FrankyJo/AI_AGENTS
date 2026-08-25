"""
Розрахунок вартості прогону.

Ціни — за мільйон токенів, станом на 2026-08. Правити тут, якщо змінились.
"""

PRICES = {
    "claude-sonnet-4-6": {"in": 3.00, "out": 15.00},
    "claude-haiku-4-5-20251001": {"in": 1.00, "out": 5.00},
}


def usd(by_model: dict) -> float:
    total = 0.0
    for model, u in by_model.items():
        p = PRICES.get(model)
        if not p:
            continue
        total += u["in"] / 1e6 * p["in"] + u["out"] / 1e6 * p["out"]
    return round(total, 6)


def aggregate(records: list) -> dict:
    """Сумує by_model з кількох записів usage_log (кожен — {"by_model": {...}})
    в один by_model-словник, придатний для usd()/breakdown()."""
    total = {}
    for r in records:
        for model, u in r["by_model"].items():
            m = total.setdefault(model, {"calls": 0, "in": 0, "out": 0})
            m["calls"] += u["calls"]
            m["in"] += u["in"]
            m["out"] += u["out"]
    return total


def breakdown(by_model: dict) -> list:
    rows = []
    for model, u in by_model.items():
        p = PRICES.get(model, {"in": 0, "out": 0})
        c = u["in"] / 1e6 * p["in"] + u["out"] / 1e6 * p["out"]
        rows.append({"model": model, "calls": u["calls"],
                     "in": u["in"], "out": u["out"], "usd": round(c, 6)})
    return sorted(rows, key=lambda r: -r["usd"])
