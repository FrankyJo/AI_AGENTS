"""
База вправ — завантажується з exercises-dataset/data/exercises.json (1324
вправи з описом і гіфкою кожна). Джерело правди для агента: він зобов'язаний
брати вправи звідси, а не вигадувати (див. list_exercises у backend.py).

Датасет не має власного contraindications — теги зон/травм (lower_back, knee,
shoulder, neck, wrist, elbow, ankle, hip; ті самі, що використовує
add_constraint) виводяться ТУТ евристикою за body_part/target/secondary_muscles
(_infer_contraindications). Це наближення, не медичний огляд: воно ловить
очевидні механічні зв'язки (жим лежачи -> плече, присід -> коліно, тяга з
прямими ногами -> поперек через secondary_muscles), але не замінює здоровий
глузд. Якщо для конкретної травми список виглядає підозріло — краще
перевірити вручну й підправити мапінг нижче.
"""

import json
import pathlib

DATASET_ROOT = pathlib.Path(__file__).resolve().parent.parent / "exercises-dataset"
DATASET_PATH = DATASET_ROOT / "data" / "exercises.json"

# body_part -> наш bucket для фільтра list_exercises(muscle_group=...)
BODY_PART_TO_MUSCLE_GROUP = {
    "плечова частина рук": "руки",
    "передпліччя": "руки",
    "стегна": "ноги",
    "гомілки": "ноги",
    "спина": "спина",
    "талія": "кор",
    "груди": "груди",
    "плечі": "плечі",
    "кардіо": "кардіо",
    "шия": "шия",
}

# кардіо-тренажери, що фактично навантажують поперек (веслування), а не коліно
_ROWING_EQUIPMENT = {"веслувальний тренажер", "гребний тренажер", "ергометр для верхньої частини тіла"}


def _infer_contraindications(ex: dict) -> list:
    body_part = ex["body_part"]
    target = ex["target"]
    secondary = set(ex.get("secondary_muscles", []))
    tags = set()

    if body_part == "груди" or body_part == "плечі":
        tags.add("shoulder")
    elif body_part == "плечова частина рук":
        tags.add("elbow")
    elif body_part == "передпліччя":
        tags.add("wrist")
    elif body_part == "гомілки":
        tags.add("ankle")
    elif body_part == "спина":
        tags.add("lower_back")
        if "обертальна манжета плеча" in secondary or "плеч" in ex.get("muscle_group", ""):
            tags.add("shoulder")
    elif body_part == "талія":
        tags.add("lower_back")
    elif body_part == "шия":
        tags.add("neck")
    elif body_part == "стегна":
        if target == "glutes":
            tags.add("hip")
        else:                                       # quads, hamstrings, adductors, abductors
            tags.add("knee")
    elif body_part == "кардіо":
        tags.add("lower_back" if ex.get("equipment") in _ROWING_EQUIPMENT else "knee")

    if "поперек" in secondary:                       # напр. тяга/розгинання на прямих ногах
        tags.add("lower_back")

    return sorted(tags)


def _load_exercises() -> list:
    raw = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    exercises = []
    for ex in raw:
        gif_path = DATASET_ROOT / ex["gif_url"]
        image_path = DATASET_ROOT / ex["image"]
        exercises.append({
            "name": ex["name"],
            "muscle_group": BODY_PART_TO_MUSCLE_GROUP.get(ex["body_part"], ex["body_part"]),
            "equipment": [ex["equipment"]],
            "contraindications": _infer_contraindications(ex),
            "target": ex["target"],
            "description": ex["instructions"]["uk"],
            "steps": ex["instruction_steps"]["uk"],
            "gif_path": str(gif_path) if gif_path.exists() else None,
            "image_path": str(image_path) if image_path.exists() else None,
        })
    return exercises


EXERCISES = _load_exercises()
