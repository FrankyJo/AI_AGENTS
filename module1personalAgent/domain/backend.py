"""
Інструменти персонального тренера. Сховище — storage/store.py (JSON на
кожного користувача Telegram).

chat_id прокидується через contextvar, а не через аргументи інструментів:
модель не повинна і не може вказати чужий chat_id — він прив'язується на рівні
бота/CLI до виклику run_agent (див. set_chat_id), а не приходить від LLM.
"""

import contextvars
import datetime

from domain.exercises import EXERCISES
from storage import store

_chat_id_var = contextvars.ContextVar("chat_id", default=None)


def set_chat_id(chat_id) -> None:
    _chat_id_var.set(str(chat_id))


def _cid() -> str:
    cid = _chat_id_var.get()
    if cid is None:
        raise RuntimeError("chat_id не встановлено — виклич set_chat_id() перед run_agent()")
    return cid


def _constraint_tags() -> set:
    data = store.load(_cid())
    return {c["tag"] for c in data["profile"]["constraints"]}


# ── профіль ──────────────────────────────────────────────────
def get_profile() -> dict:
    return store.load(_cid())["profile"]


def update_profile(goals: str = None, level: str = None, equipment: list = None) -> dict:
    data = store.load(_cid())
    if goals is not None:
        data["profile"]["goals"] = goals
    if level is not None:
        data["profile"]["level"] = level
    if equipment is not None:
        data["profile"]["equipment"] = equipment
    store.save(_cid(), data)
    return data["profile"]


def add_constraint(tag: str, note: str = "") -> dict:
    data = store.load(_cid())
    tags = {c["tag"] for c in data["profile"]["constraints"]}
    if tag not in tags:
        data["profile"]["constraints"].append(
            {"tag": tag, "note": note, "since": datetime.date.today().isoformat()})
        store.save(_cid(), data)
    return data["profile"]


def remove_constraint(tag: str) -> dict:
    data = store.load(_cid())
    data["profile"]["constraints"] = [
        c for c in data["profile"]["constraints"] if c["tag"] != tag]
    store.save(_cid(), data)
    return data["profile"]


# ── база вправ ────────────────────────────────────────────────
def list_exercises(muscle_group: str = None, equipment: str = None) -> dict:
    banned = _constraint_tags()
    items = EXERCISES
    if muscle_group:
        items = [e for e in items if e["muscle_group"] == muscle_group]
    if equipment:
        items = [e for e in items if equipment in e["equipment"]]
    safe = [e for e in items if not (banned & set(e["contraindications"]))]
    excluded = [e["name"] for e in items if banned & set(e["contraindications"])]
    return {"exercises": safe, "excluded_due_to_constraints": excluded}


# ── програма тренувань ──────────────────────────────────────
def get_program() -> dict:
    return store.load(_cid())["program"]


def set_program(name: str, days: list) -> dict:
    data = store.load(_cid())
    data["program"] = {"name": name, "days": days}
    store.save(_cid(), data)
    return data["program"]


def swap_exercise(day: str, old_exercise: str, new_exercise: str, reason: str = "") -> dict:
    data = store.load(_cid())
    for d in data["program"]["days"]:
        if d["day"] != day:
            continue
        for ex in d["exercises"]:
            if ex["name"] == old_exercise:
                ex["name"] = new_exercise
                ex["swapped_reason"] = reason
                store.save(_cid(), data)
                return {"ok": True, "day": day, "old": old_exercise, "new": new_exercise}
        return {"error": "exercise_not_found", "day": day, "old_exercise": old_exercise}
    return {"error": "day_not_found", "day": day}


# ── журнал тренувань ────────────────────────────────────────
def log_workout(date: str, exercises: list, day: str = "", note: str = "") -> dict:
    data = store.load(_cid())
    entry = {"date": date, "day": day, "exercises": exercises, "note": note}
    data["history"].append(entry)
    store.save(_cid(), data)
    return {"ok": True, "logged": entry, "total_workouts": len(data["history"])}


def get_history(limit: int = 5) -> dict:
    data = store.load(_cid())
    hist = data["history"][-limit:]
    return {"count": len(hist), "history": hist, "total_workouts": len(data["history"])}


IMPL = {
    "get_profile": get_profile,
    "update_profile": update_profile,
    "add_constraint": add_constraint,
    "remove_constraint": remove_constraint,
    "list_exercises": list_exercises,
    "get_program": get_program,
    "set_program": set_program,
    "swap_exercise": swap_exercise,
    "log_workout": log_workout,
    "get_history": get_history,
}


def dispatch(name: str, args: dict) -> dict:
    fn = IMPL.get(name)
    if not fn:
        return {"error": f"unknown_tool:{name}"}
    try:
        return fn(**args)
    except TypeError as e:
        return {"error": f"bad_args: {e}"}


# ── схеми для Claude ─────────────────────────────────────────
def _schema(name, desc, props, required):
    return {"name": name, "description": desc,
            "input_schema": {"type": "object", "properties": props, "required": required}}


TOOL_SCHEMAS = {
    "get_profile": _schema(
        "get_profile",
        "Повертає профіль користувача: цілі, рівень, доступне обладнання та "
        "поточні обмеження/травми. Викликай ПЕРЕД тим як складати чи змінювати "
        "програму тренувань.",
        {}, []),
    "update_profile": _schema(
        "update_profile",
        "Оновлює цілі, рівень підготовки або список доступного обладнання. "
        "Не використовуй для травм/обмежень — для них є add_constraint.",
        {"goals": {"type": "string", "description": "Мета тренувань, наприклад «набір маси»"},
         "level": {"type": "string", "description": "Рівень: новачок/середній/просунутий"},
         "equipment": {"type": "array", "items": {"type": "string"},
                        "description": "Доступне обладнання, наприклад [\"гантелі\", \"турнік\"]"}},
        []),
    "add_constraint": _schema(
        "add_constraint",
        "Записує фізичне обмеження або травму користувача (наприклад біль у "
        "спині, коліні, плечі). Викликай одразу, як тільки користувач про неї "
        "згадав — це має вплинути на всі подальші рекомендації вправ. "
        "Використовуй короткий тег зони: lower_back, knee, shoulder, neck, wrist, "
        "elbow, ankle, hip.",
        {"tag": {"type": "string", "description": "Короткий тег зони/проблеми"},
         "note": {"type": "string", "description": "Що саме болить і за яких рухів"}},
        ["tag"]),
    "remove_constraint": _schema(
        "remove_constraint",
        "Знімає обмеження, коли користувач каже, що проблема минула.",
        {"tag": {"type": "string", "description": "Тег обмеження, яке треба зняти"}},
        ["tag"]),
    "list_exercises": _schema(
        "list_exercises",
        "Повертає вправи з бази, ВЖЕ відфільтровані за поточними обмеженнями "
        "профілю (небезпечні при травмах користувача виключені й перелічені "
        "окремо в excluded_due_to_constraints). Використовуй, щоб підібрати "
        "вправи для нової програми або знайти заміну — не вигадуй вправи, "
        "яких немає в цьому списку.",
        {"muscle_group": {"type": "string",
                            "description": "Група м'язів: ноги, спина, груди, плечі, руки, кор, кардіо"},
         "equipment": {"type": "string", "description": "Фільтр за конкретним обладнанням"}},
        []),
    "get_program": _schema(
        "get_program", "Повертає поточну збережену програму тренувань користувача.",
        {}, []),
    "set_program": _schema(
        "set_program",
        "Повністю зберігає (створює або замінює цілком) програму тренувань. "
        "Вправи мають бути взяті з list_exercises, а не вигадані.",
        {"name": {"type": "string", "description": "Назва програми, наприклад «Спліт на 3 дні»"},
         "days": {"type": "array", "description": "Дні програми",
                    "items": {"type": "object",
                               "properties": {
                                   "day": {"type": "string"},
                                   "exercises": {
                                       "type": "array",
                                       "items": {
                                           "type": "object",
                                           "properties": {
                                               "name": {"type": "string"},
                                               "sets": {"type": "integer"},
                                               "reps": {"type": "string"},
                                               "notes": {"type": "string"}},
                                           "required": ["name", "sets", "reps"]}}},
                               "required": ["day", "exercises"]}}},
        ["name", "days"]),
    "swap_exercise": _schema(
        "swap_exercise",
        "Замінює одну вправу в конкретному дні збереженої програми на іншу. "
        "Нова вправа має бути підібрана через list_exercises з урахуванням "
        "обмежень.",
        {"day": {"type": "string", "description": "Назва дня програми, як у get_program"},
         "old_exercise": {"type": "string", "description": "Точна назва вправи, яку замінюємо"},
         "new_exercise": {"type": "string", "description": "Точна назва нової вправи"},
         "reason": {"type": "string", "description": "Чому міняємо"}},
        ["day", "old_exercise", "new_exercise"]),
    "log_workout": _schema(
        "log_workout",
        "Записує виконане тренування в історію — викликай, коли користувач "
        "розповідає, що і як він сьогодні потренував.",
        {"date": {"type": "string", "description": "Дата у форматі РРРР-ММ-ДД"},
         "day": {"type": "string", "description": "Назва дня програми, якщо застосовно"},
         "exercises": {
             "type": "array",
             "items": {
                 "type": "object",
                 "properties": {
                     "name": {"type": "string"},
                     "sets": {"type": "integer"},
                     "reps": {"type": "string"},
                     "weight": {"type": "string"},
                     "notes": {"type": "string"}},
                 "required": ["name"]}},
         "note": {"type": "string", "description": "Загальне самопочуття, біль, прогрес"}},
        ["date", "exercises"]),
    "get_history": _schema(
        "get_history",
        "Повертає останні N записів історії тренувань для аналізу прогресу.",
        {"limit": {"type": "integer", "description": "Скільки останніх тренувань повернути"}},
        []),
}

ALL_TOOLS = list(TOOL_SCHEMAS.keys())


def tools() -> list:
    return [TOOL_SCHEMAS[n] for n in ALL_TOOLS]
