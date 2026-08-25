"""
Інструменти персонального тренера. Сховище — storage/store.py (JSON на
кожного користувача Telegram).

chat_id прокидується через contextvar, а не через аргументи інструментів:
модель не повинна і не може вказати чужий chat_id — він прив'язується на рівні
бота/CLI до виклику run_agent (див. set_chat_id), а не приходить від LLM.
"""

import contextvars
import datetime
import random

from domain.exercises import EXERCISES
from domain.progress import normalize_sets
from storage import store

_chat_id_var = contextvars.ContextVar("chat_id", default=None)

# скільки підходів очікувати, якщо вправи немає в збереженій програмі
DEFAULT_EXPECTED_SETS = 4

# як часто нагадувати записати вагу/заміри тіла — раз на 1-2 тижні, врозкид
CHECK_IN_MIN_DAYS = 7
CHECK_IN_MAX_DAYS = 14

# скільки останніх пар user/assistant тримати в історії діалогу (обмежує
# зростання контексту й вартості — старіші репліки просто забуваються)
MAX_HISTORY_TURNS = 8


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


# ── історія діалогу (не інструмент для LLM — керує bot/telegram_bot.py) ──
def get_conversation() -> list:
    return store.load(_cid()).get("conversation", [])


def append_conversation(user_text: str, assistant_text: str) -> list:
    """Повертає репліки, що випали за межі вікна MAX_HISTORY_TURNS (порожній
    список, якщо нічого не випало) — виклик передає їх у summarize_into_notes,
    щоб не втрачати старий контекст безслідно, а стиснути в memory_notes."""
    data = store.load(_cid())
    data.setdefault("conversation", [])
    data["conversation"].append({"role": "user", "content": user_text})
    data["conversation"].append({"role": "assistant", "content": assistant_text})

    limit = MAX_HISTORY_TURNS * 2
    dropped = data["conversation"][:-limit] if len(data["conversation"]) > limit else []
    data["conversation"] = data["conversation"][-limit:]

    store.save(_cid(), data)
    return dropped


def get_memory_notes() -> str:
    return store.load(_cid()).get("memory_notes", "")


def update_memory_notes(notes: str) -> None:
    data = store.load(_cid())
    data["memory_notes"] = notes
    store.save(_cid(), data)


# ── профіль ──────────────────────────────────────────────────
def get_profile() -> dict:
    return store.load(_cid())["profile"]


def update_profile(name: str = None, goals: str = None, level: str = None, equipment: list = None) -> dict:
    data = store.load(_cid())
    if name is not None:
        data["profile"]["name"] = name
    if goals is not None:
        data["profile"]["goals"] = goals
    if level is not None:
        data["profile"]["level"] = level
    if equipment is not None:
        data["profile"]["equipment"] = equipment
    store.save(_cid(), data)
    return data["profile"]


def _default_body_metrics() -> dict:
    return {"weight_kg": None, "measurements": {}, "updated_at": None, "next_check_in": None}


def _schedule_next_check_in(bm: dict) -> None:
    days = random.randint(CHECK_IN_MIN_DAYS, CHECK_IN_MAX_DAYS)
    bm["next_check_in"] = (datetime.date.today() + datetime.timedelta(days=days)).isoformat()


def update_body_metrics(weight_kg: float = None, measurements: dict = None) -> dict:
    data = store.load(_cid())
    bm = data["profile"].setdefault("body_metrics", _default_body_metrics())
    if weight_kg is not None:
        bm["weight_kg"] = weight_kg
    if measurements:
        bm["measurements"].update(measurements)
    bm["updated_at"] = datetime.date.today().isoformat()
    _schedule_next_check_in(bm)               # користувач сам дав дані -> наступне нагадування відсунуто
    store.save(_cid(), data)
    return data["profile"]


# ── нагадування записати вагу/заміри (використовує планувальник бота, не LLM) ─
def is_check_in_due() -> bool:
    data = store.load(_cid())
    next_check_in = data["profile"].get("body_metrics", {}).get("next_check_in")
    return next_check_in is None or next_check_in <= datetime.date.today().isoformat()


def mark_check_in_sent() -> None:
    data = store.load(_cid())
    bm = data["profile"].setdefault("body_metrics", _default_body_metrics())
    _schedule_next_check_in(bm)
    store.save(_cid(), data)


def list_known_chat_ids() -> list:
    return store.list_chat_ids()


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
# датасет великий (1324 вправи) — list_exercises віддає короткі картки й
# обрізає видачу, щоб один виклик не роздув контекст/вартість прогону;
# повний опис+гіфка для КОНКРЕТНОЇ вправи — окремо через get_exercise_details.
LIST_EXERCISES_DEFAULT_LIMIT = 15
LIST_EXERCISES_MAX_LIMIT = 30


def _compact(e: dict) -> dict:
    return {"name": e["name"], "muscle_group": e["muscle_group"],
            "equipment": e["equipment"], "contraindications": e["contraindications"]}


def list_exercises(muscle_group: str = None, equipment: str = None,
                    limit: int = LIST_EXERCISES_DEFAULT_LIMIT) -> dict:
    banned = _constraint_tags()
    items = EXERCISES
    if muscle_group:
        items = [e for e in items if e["muscle_group"] == muscle_group]
    if equipment:
        items = [e for e in items if equipment in e["equipment"]]
    safe = [e for e in items if not (banned & set(e["contraindications"]))]
    excluded_names = [e["name"] for e in items if banned & set(e["contraindications"])]

    limit = max(1, min(limit, LIST_EXERCISES_MAX_LIMIT))
    return {"exercises": [_compact(e) for e in safe[:limit]],
            "total_matching": len(safe),
            "excluded_due_to_constraints": excluded_names[:limit],
            "excluded_total": len(excluded_names)}


def get_exercise_details(name: str) -> dict:
    for e in EXERCISES:
        if e["name"] == name:
            return {"name": e["name"], "muscle_group": e["muscle_group"], "target": e["target"],
                    "equipment": e["equipment"], "description": e["description"], "steps": e["steps"],
                    "contraindications": e["contraindications"],
                    "gif_path": e["gif_path"], "image_path": e["image_path"]}
    return {"error": "exercise_not_found", "name": name}


# ── програма тренувань ──────────────────────────────────────
def get_program() -> dict:
    return store.load(_cid())["program"]


def set_program(name: str, days: list, program_type: str = "") -> dict:
    data = store.load(_cid())
    data["program"] = {"name": name, "type": program_type, "days": days,
                        "updated_at": datetime.date.today().isoformat()}
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


def get_exercise_history(exercise: str, limit: int = 5) -> dict:
    data = store.load(_cid())
    occurrences = []
    for entry in reversed(data["history"]):
        for ex in entry["exercises"]:
            if ex["name"] == exercise:
                occurrences.append({"date": entry["date"], "sets": normalize_sets(ex)})
        if len(occurrences) >= limit:
            break
    return {"exercise": exercise, "occurrences": occurrences[:limit]}


# ── підходи в реальному часі ─────────────────────────────────
def _find_expected_sets(data: dict, day: str, exercise: str) -> int:
    for d in data["program"]["days"]:
        if day and d["day"] != day:
            continue
        for ex in d["exercises"]:
            if ex["name"] == exercise:
                return ex.get("sets") or DEFAULT_EXPECTED_SETS
    return DEFAULT_EXPECTED_SETS


def log_set(exercise: str, weight: str, reps: str, day: str = "") -> dict:
    data = store.load(_cid())
    active = data.get("active_set_log")
    if not active or active["exercise"] != exercise:
        active = {"exercise": exercise, "day": day, "sets": [],
                   "expected_sets": _find_expected_sets(data, day, exercise)}
    active["sets"].append({"weight": weight, "reps": reps})
    data["active_set_log"] = active
    store.save(_cid(), data)

    logged = len(active["sets"])
    expected = active["expected_sets"]
    return {"exercise": exercise, "logged_sets": logged, "expected_sets": expected,
            "remaining": max(0, expected - logged)}


def finish_exercise_set_log(early_stop: bool = False, note: str = "") -> dict:
    data = store.load(_cid())
    active = data.get("active_set_log")
    if not active:
        return {"error": "no_active_exercise"}

    entry = {"date": datetime.date.today().isoformat(), "day": active.get("day", ""),
              "exercises": [{"name": active["exercise"], "sets": len(active["sets"]),
                              "sets_detail": active["sets"]}],
              "note": note, "early_stop": early_stop}
    data["history"].append(entry)
    data["active_set_log"] = None
    store.save(_cid(), data)
    return {"ok": True, "exercise": active["exercise"], "total_sets": len(active["sets"]),
            "early_stop": early_stop, "sets_detail": active["sets"]}


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
    "log_set": log_set,
    "finish_exercise_set_log": finish_exercise_set_log,
    "update_body_metrics": update_body_metrics,
    "get_exercise_history": get_exercise_history,
    "get_exercise_details": get_exercise_details,
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
        "Оновлює ім'я користувача, цілі, рівень підготовки або список "
        "доступного обладнання. Не використовуй для травм/обмежень — для них "
        "є add_constraint.",
        {"name": {"type": "string",
                    "description": "Ім'я користувача або як до нього звертатися"},
         "goals": {"type": "string", "description": "Мета тренувань, наприклад «набір маси»"},
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
        "Повертає короткі картки вправ (назва/група м'язів/обладнання) з бази "
        "1324 вправ, ВЖЕ відфільтровані за поточними обмеженнями профілю "
        "(небезпечні при травмах користувача виключені й перелічені окремо в "
        "excluded_due_to_constraints, з кількістю у excluded_total). Видача "
        "обрізається лімітом (total_matching показує скільки насправді "
        "підходить) — звужуй muscle_group/equipment, а не намагайся отримати "
        "все одразу. Використовуй, щоб підібрати вправи для програми чи "
        "заміни — не вигадуй вправи, яких немає в цьому списку. Щоб отримати "
        "повний опис і гіфку конкретної вправи — get_exercise_details.",
        {"muscle_group": {"type": "string",
                            "description": "Група м'язів: ноги, спина, груди, плечі, руки, кор, кардіо, шия"},
         "equipment": {"type": "string", "description": "Фільтр за конкретним обладнанням"},
         "limit": {"type": "integer",
                    "description": f"Скільки вправ повернути (типово {LIST_EXERCISES_DEFAULT_LIMIT}, "
                                    f"максимум {LIST_EXERCISES_MAX_LIMIT})"}},
        []),
    "get_exercise_details": _schema(
        "get_exercise_details",
        "Повертає повний опис вправи (покроково) і шлях до гіфки/фото — "
        "викликай ПЕРЕД тим як пропонуєш користувачу зробити конкретну вправу "
        "прямо зараз (наживо, у процесі тренування), щоб бот міг показати "
        "техніку і прикріпити гіфку. Не викликай для кожної вправи в усій "
        "програмі одразу — лише для тієї, яку користувач буде робити зараз.",
        {"name": {"type": "string", "description": "Точна назва вправи, як у list_exercises"}},
        ["name"]),
    "get_program": _schema(
        "get_program", "Повертає поточну збережену програму тренувань користувача.",
        {}, []),
    "set_program": _schema(
        "set_program",
        "Повністю зберігає (створює або замінює цілком) програму тренувань. "
        "Вправи мають бути взяті з list_exercises, а не вигадані.",
        {"name": {"type": "string", "description": "Назва програми, наприклад «Спліт на 3 дні»"},
         "program_type": {"type": "string",
                            "description": "Тип програми: \"full_body\" або \"split\""},
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
    "log_set": _schema(
        "log_set",
        "Фіксує ОДИН підхід вправи в реальному часі — викликай щоразу, як "
        "користувач повідомляє результат окремого підходу під час тренування "
        "(наприклад «10 на 12», «10кг на 12», «12 на 8»), а не наприкінці "
        "тренування одним повідомленням. Перший виклик для вправи починає новий "
        "підрахунок; якщо назва вправи змінилась — починається новий підрахунок "
        "для неї. У відповіді remaining показує, скільки підходів ще очікується.",
        {"exercise": {"type": "string", "description": "Точна назва вправи"},
         "weight": {"type": "string", "description": "Вага цього підходу, наприклад «10кг»"},
         "reps": {"type": "string", "description": "Кількість повторів цього підходу"},
         "day": {"type": "string",
                  "description": "Назва дня програми, якщо відомо — щоб узяти звідти "
                                  "очікувану кількість підходів"}},
        ["exercise", "weight", "reps"]),
    "finish_exercise_set_log": _schema(
        "finish_exercise_set_log",
        "Завершує поточний підрахунок підходів і записує вправу в історію "
        "тренувань. Викликай, коли remaining з log_set дійшло до 0, АБО коли "
        "користувач явно каже, що більше підходів робити не буде — тоді передай "
        "early_stop=true.",
        {"early_stop": {"type": "boolean",
                          "description": "true, якщо користувач зупинився раніше "
                                          "очікуваної кількості підходів"},
         "note": {"type": "string", "description": "Додаткова примітка, якщо є"}},
        []),
    "update_body_metrics": _schema(
        "update_body_metrics",
        "Зберігає антропометричні дані користувача: вагу тіла та обхвати (ноги, "
        "руки, талія тощо). Викликай під час короткого анкетування перед першою "
        "програмою, і повторно, коли користувач ділиться новими замірами.",
        {"weight_kg": {"type": "number", "description": "Вага тіла в кілограмах"},
         "measurements": {"type": "object",
                            "description": "Обхвати в сантиметрах, довільні ключі, "
                                            "наприклад {\"талія\": \"80\", \"стегно\": \"55\"}"}},
        []),
    "get_exercise_history": _schema(
        "get_exercise_history",
        "Повертає останні N разів, коли користувач виконував конкретну вправу, з "
        "вагою і повторами кожного підходу. Використовуй перед тим як пропонувати "
        "вагу для цієї вправи — щоб порадити трохи більше, ніж минулого разу "
        "(прогресивне перевантаження), а не повторювати ту саму вагу.",
        {"exercise": {"type": "string", "description": "Точна назва вправи"},
         "limit": {"type": "integer", "description": "Скільки останніх разів повернути"}},
        ["exercise"]),
}

ALL_TOOLS = list(TOOL_SCHEMAS.keys())


def tools() -> list:
    return [TOOL_SCHEMAS[n] for n in ALL_TOOLS]
