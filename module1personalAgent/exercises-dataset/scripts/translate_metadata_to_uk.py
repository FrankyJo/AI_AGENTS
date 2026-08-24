#!/usr/bin/env python3
"""
Translate exercise metadata values from English to Ukrainian via local dictionaries
and Ollama for exercise names.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Iterable


DEFAULT_MODEL = "gemma4:latest"
DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
DEFAULT_CACHE = Path("/private/tmp/exercise_names_uk_cache.json")

CATEGORY_BODY_PART_TRANSLATIONS = {
    "back": "спина",
    "cardio": "кардіо",
    "chest": "груди",
    "lower arms": "передпліччя",
    "lower legs": "гомілки",
    "neck": "шия",
    "shoulders": "плечі",
    "upper arms": "плечова частина рук",
    "upper legs": "стегна",
    "waist": "талія",
}

EQUIPMENT_TRANSLATIONS = {
    "assisted": "з допомогою",
    "band": "еластична стрічка",
    "barbell": "штанга",
    "body weight": "власна вага",
    "bosu ball": "мʼяч BOSU",
    "cable": "блочний тренажер",
    "dumbbell": "гантель",
    "elliptical machine": "еліптичний тренажер",
    "ez barbell": "EZ-штанга",
    "hammer": "молот",
    "kettlebell": "гиря",
    "leverage machine": "важільний тренажер",
    "medicine ball": "медбол",
    "olympic barbell": "олімпійська штанга",
    "resistance band": "еластична стрічка",
    "roller": "ролер",
    "rope": "канат",
    "skierg machine": "лижний ергометр",
    "sled machine": "санний тренажер",
    "smith machine": "машина Сміта",
    "stability ball": "фітбол",
    "stationary bike": "велотренажер",
    "stepmill machine": "сходовий тренажер",
    "tire": "шина",
    "trap bar": "треп-гриф",
    "upper body ergometer": "ергометр для верхньої частини тіла",
    "weighted": "з обтяженням",
    "wheel roller": "ролик для преса",
}

MUSCLE_TRANSLATIONS = {
    "abdominals": "мʼязи преса",
    "ankle stabilizers": "стабілізатори щиколотки",
    "ankles": "щиколотки",
    "back": "спина",
    "biceps": "біцепси",
    "brachialis": "плечовий мʼяз",
    "calves": "литкові мʼязи",
    "chest": "грудні мʼязи",
    "core": "мʼязи кора",
    "deltoids": "дельтоподібні мʼязи",
    "feet": "стопи",
    "forearms": "передпліччя",
    "glutes": "сідничні мʼязи",
    "grip muscles": "мʼязи хвату",
    "groin": "пахові мʼязи",
    "hamstrings": "задня поверхня стегна",
    "hands": "кисті",
    "hip flexors": "згиначі стегна",
    "inner thighs": "внутрішня поверхня стегна",
    "latissimus dorsi": "найширші мʼязи спини",
    "lats": "найширші мʼязи спини",
    "lower abs": "нижній прес",
    "lower back": "поперек",
    "obliques": "косі мʼязи живота",
    "quadriceps": "квадрицепси",
    "rear deltoids": "задні дельти",
    "rhomboids": "ромбоподібні мʼязи",
    "rotator cuff": "обертальна манжета плеча",
    "shins": "передня частина гомілки",
    "shoulders": "плечі",
    "soleus": "камбалоподібний мʼяз",
    "sternocleidomastoid": "грудинно-ключично-соскоподібний мʼяз",
    "trapezius": "трапецієподібний мʼяз",
    "traps": "трапецієподібний мʼяз",
    "triceps": "трицепси",
    "upper back": "верх спини",
    "upper chest": "верх грудних мʼязів",
    "wrist extensors": "розгиначі запʼястка",
    "wrist flexors": "згиначі запʼястка",
    "wrists": "запʼястки",
}

SYSTEM_PROMPT = """You are a professional English-to-Ukrainian translator for a fitness exercise database. Translate exercise names into natural Ukrainian.
Rules:
- Return valid JSON only, exactly {"translations": [ ... ]}.
- The translations array must have the same length and order as input.
- Translate the exercise name, not the instructions.
- Preserve numbers, angles, version markers such as v. 2, and parenthetical gender markers as (чоловіки) or (жінки).
- Preserve brand-like equipment terms only when Ukrainian fitness usage normally keeps them: BOSU, EZ, JM, Svend, Zottman, Pendlay, Gironda, Janda, Maltese, Planche, Skierg, T-bar, V-bar.
- Use consistent Ukrainian fitness terminology: barbell = штанга, dumbbell = гантель, kettlebell = гиря, cable = блочний тренажер, band/resistance band = еластична стрічка, bodyweight = з власною вагою, pull-up/chin-up = підтягування, push-up = віджимання, sit-up = підйом тулуба, crunch = скручування, squat = присідання, lunge = випад, row = тяга, curl = згинання рук, press = жим, fly = розведення рук, raise = підйом, pulldown = тяга зверху, pushdown = розгинання вниз, dip = віджимання на брусах, calf raise = підйом на носки.
- No explanations, no extra keys, no English text except unavoidable names/abbreviations.
"""

NAME_REPLACEMENTS = {
    "all fours": "на четвереньках",
    "pull up": "підтягування",
    "pull ups": "підтягування",
    "pull-ups": "підтягування",
    "push up": "віджимання",
    "push-ups": "віджимання",
    "chin ups": "підтягування зворотним хватом",
    "chin up": "підтягування зворотним хватом",
    "chin-ups": "підтягування зворотним хватом",
    "curl up": "скручування",
    "curl-up": "скручування",
    "body up": "підйом тіла",
    "body-up": "підйом тіла",
    "step up": "зашагування",
    "drop jump": "стрибок з приземленням",
    "box jump": "стрибок на коробку",
    "backward jump": "стрибок назад",
    "forward jump": "стрибок вперед",
    "clap push up": "віджимання з плеском",
    "deep push up": "глибоке віджимання",
    "modified push up": "модифіковане віджимання",
    "wide hand push up": "віджимання з широкою постановкою рук",
    "close grip": "вузьким хватом",
    "wide grip": "широким хватом",
    "reverse grip": "зворотним хватом",
    "neutral grip": "нейтральним хватом",
    "palm rotational": "з обертанням долоні",
    "palms down": "долонями вниз",
    "palms up": "долонями вгору",
    "palms in": "долонями всередину",
    "palm in": "долонею всередину",
    "straight arm": "прямою рукою",
    "two arm": "двома руками",
    "one arm": "однією рукою",
    "single arm": "однією рукою",
    "bent arm": "зігнутою рукою",
    "full range of motion": "повна амплітуда руху",
    "range of motion": "амплітуда руху",
    "cross over": "кросовер",
    "cross-over": "кросовер",
    "cross body": "навхрест",
    "up down": "вгору-вниз",
    "up-down": "вгору-вниз",
    "pull through": "протягування",
    "pass through": "передача через",
    "chest tap": "торкання грудей",
    "leg press": "жим ногами",
    "calf press": "жим носками",
    "toe raise": "підйом носків",
    "ab rollerout": "викочування ролика для преса",
    "walking on": "ходьба на",
    "stationary bike": "велотренажер",
    "cycle cross trainer": "еліптичний тренажер",
    "ski ergometer": "лижний ергометр",
    "captains chair": "римський стілець",
    "dip pull up cage": "станція для брусів і підтягувань",
    "dip-pull-up cage": "станція для брусів і підтягувань",
    "tennis ball": "тенісний мʼяч",
    "stork stance": "стійка на одній нозі",
    "goblet squat": "гоблет-присідання",
    "pistol squat": "пістолетик",
    "curtsey squat": "реверанс-присідання",
    "potty squat": "глибоке присідання",
    "split squats": "спліт-присідання",
    "half sit-up": "напівпідйом тулуба",
    "quarter sit-up": "чверть-підйом тулуба",
    "full sit-up": "повний підйом тулуба",
    "leg raise": "підйом ніг",
    "leg-hip raise": "підйом ніг і тазу",
    "knee raise": "підйом колін",
    "leg curl": "згинання ніг",
    "leg extension": "розгинання ніг",
    "hip adduction": "приведення стегна",
    "hip abduction": "відведення стегна",
    "shoulder internal rotation": "внутрішня ротація плеча",
    "shoulder external rotation": "зовнішня ротація плеча",
    "gluteus": "сідничний мʼяз",
    "adductor": "привідний мʼяз",
    "skull": "французький",
    "lifting": "підйом",
    "bradford": "Бредфорд",
    "concentration": "концентрований",
    "russian": "російський",
    "raised": "піднята",
    "bowling": "боулінг",
    "contralateral": "контралатеральний",
    "across face": "поперек обличчя",
    "femoral": "стегновий",
    "pronated": "пронованим хватом",
    "supinated": "супінованим хватом",
    "pronation": "пронація",
    "supination": "супінація",
    "pronate": "пронований",
    "rotate": "обертання",
    "stepbox": "степ-платформа",
    "around world": "навколо світу",
    "above head": "над головою",
    "balance": "баланс",
    "supported": "з опорою",
    "waiter": "офіціант",
    "dynamic": "динамічний",
    "elbow-to-knee": "лікоть до коліна",
    "elevator": "ліфт",
    "hug": "обійми",
    "pyramid": "піраміда",
    "between ankles": "між щиколотками",
    "between knees": "між колінами",
    "legged": "нога",
    "diagonal": "діагональний",
    "pike": "пікою",
    "anti gravity": "антигравітаційний",
    "face press": "жим до обличчя",
    "heel touchers": "торкання пʼят",
    "toe touch": "торкання носків",
    "toe touchers": "торкання носків",
    "side bend": "бічний нахил",
    "air bike": "велосипед лежачи",
    "arms apart": "руки в сторони",
    "arms overhead": "руки над головою",
    "arm slingers": "підйоми ніг у висі з лямками",
    "bent knee": "зігнуті коліна",
    "straight legs": "прямі ноги",
    "straight leg": "пряма нога",
    "throw down": "кидок вниз",
    "motion russian twist": "російський поворот у русі",
    "parallel close grip": "паралельним вузьким хватом",
    "rectus femoris": "прямий мʼяз стегна",
    "back and forth": "вперед-назад",
    "back lever": "задній горизонтальний вис",
    "front lever": "передній горизонтальний вис",
    "pec stretch": "розтяжка грудних мʼязів",
    "balance board": "балансувальна дошка",
    "jack knife": "складаний ніж",
    "pallof press": "жим Паллофа",
    "stiff leg": "на прямих ногах",
    "straight back": "з прямою спиною",
    "good morning": "нахили зі штангою",
    "guillotine bench press": "гільйотинний жим лежачи",
    "hack squat": "гак-присідання",
    "high bar squat": "присідання з високим положенням штанги",
    "low bar squat": "присідання з низьким положенням штанги",
    "zercher squat": "присідання Зерхера",
    "glute bridge": "сідничний місток",
    "front squat": "фронтальне присідання",
    "full squat": "повне присідання",
    "jump squat": "присідання зі стрибком",
    "split squat": "спліт-присідання",
    "sissy squat": "сісі-присідання",
    "sumo squat": "сумо-присідання",
    "sumo deadlift": "сумо-станова тяга",
    "romanian deadlift": "румунська станова тяга",
    "pendlay row": "тяга Пендлея",
    "rack pull": "тяга з рами",
    "drag curl": "згинання рук протягуванням",
    "preacher curl": "згинання рук на лаві Скотта",
    "spider curl": "павуче згинання рук",
    "zottman curl": "згинання Зоттмана",
    "hammer curl": "молоткове згинання рук",
    "concentration curl": "концентроване згинання рук",
    "french press": "французький жим",
    "military press": "армійський жим",
    "bradford press": "жим Бредфорда",
    "arnold press": "жим Арнольда",
    "jm bench press": "JM-жим лежачи",
    "bench press": "жим лежачи",
    "floor press": "жим з підлоги",
    "shoulder press": "жим на плечі",
    "chest press": "жим на груди",
    "push press": "поштовховий жим",
    "upright row": "вертикальна тяга",
    "lateral raise": "латеральний підйом",
    "front raise": "підйом перед собою",
    "rear delt raise": "підйом на задні дельти",
    "rear delt row": "тяга на задні дельти",
    "reverse fly": "зворотне розведення рук",
    "wrist curl": "згинання запʼястків",
    "reverse wrist curl": "зворотне згинання запʼястків",
    "calf raise": "підйом на носки",
    "donkey calf raise": "підйом на носки в нахилі",
    "lat pulldown": "тяга зверху на найширші",
    "lateral pulldown": "латеральна тяга зверху",
    "underhand pulldown": "тяга зверху зворотним хватом",
    "triceps extension": "розгинання на трицепс",
    "tricep extension": "розгинання на трицепс",
    "triceps pushdown": "розгинання на трицепс вниз",
    "tricep pushdown": "розгинання на трицепс вниз",
    "chest dip": "віджимання на брусах для грудей",
    "triceps dip": "віджимання на брусах на трицепс",
    "side plank": "бічна планка",
    "mountain climber": "альпініст",
    "bear crawl": "ведмежа хода",
    "burpee": "бурпі",
    "butterfly yoga pose": "поза метелика",
    "dead bug": "мертвий жук",
    "diamond push-up": "діамантові віджимання",
    "handstand": "стійка на руках",
    "handstand push-up": "віджимання у стійці на руках",
    "hanging leg raise": "підйом ніг у висі",
    "hanging knee raise": "підйом колін у висі",
    "hip flexor": "згинач стегна",
    "hip raise": "підйом тазу",
    "hyperextension": "гіперекстензія",
    "inverted row": "австралійські підтягування",
    "jump rope": "стрибки зі скакалкою",
    "muscle up": "вихід силою",
    "muscle-up": "вихід силою",
    "russian twist": "російський поворот",
    "scapula push-up": "віджимання з рухом лопаток",
    "scapular pull-up": "підтягування лопатками",
    "skater hops": "стрибки ковзаняра",
    "tire flip": "перекидання шини",
    "wrist circles": "обертання запʼястками",
    "reverse-grip": "зворотним хватом",
    "wide-grip": "широким хватом",
    "close-grip": "вузьким хватом",
    "bent-over": "у нахилі",
    "step-up": "зашагування",
    "push-up": "віджимання",
    "sit-up": "підйом тулуба",
    "pull-up": "підтягування",
    "chin-up": "підтягування зворотним хватом",
    "v-up": "V-підйом",
    "y-raise": "Y-підйом",
    "t-raise": "T-підйом",
    "w-press": "W-жим",
    "rollerout": "викочування ролика",
    "skullcrusher": "французький жим лежачи",
    "skull crusher": "французький жим лежачи",
    "bodyweight": "з власною вагою",
    "dumbbells": "гантелі",
    "dumbbell": "гантель",
    "barbell": "штанга",
    "kettlebell": "гиря",
    "cable": "блочний тренажер",
    "band": "еластична стрічка",
    "resistance": "еластична",
    "medicine ball": "медбол",
    "exercise ball": "фітбол",
    "stability ball": "фітбол",
    "bosu ball": "мʼяч BOSU",
    "ez barbell": "EZ-штанга",
    "ez bar": "EZ-гриф",
    "ez-barbell": "EZ-штанга",
    "ez-bar": "EZ-гриф",
    "smith machine": "машина Сміта",
    "smith": "машина Сміта",
    "lever": "важільний тренажер",
    "sled": "санний тренажер",
    "trap bar": "треп-гриф",
    "wheel roller": "ролик для преса",
    "roller": "ролер",
    "rope": "канат",
    "bench": "лава",
    "bar": "гриф",
    "v-bar": "V-гриф",
    "t-bar": "T-гриф",
    "arm blaster": "арм-бластер",
    "arm": "рука",
    "arms": "руки",
    "curl": "згинання рук",
    "curls": "згинання рук",
    "press": "жим",
    "row": "тяга",
    "pulldown": "тяга зверху",
    "pushdown": "розгинання вниз",
    "extension": "розгинання",
    "raise": "підйом",
    "raises": "підйоми",
    "flyes": "розведення рук",
    "fly": "розведення рук",
    "dip": "віджимання на брусах",
    "dips": "віджимання на брусах",
    "squat": "присідання",
    "squats": "присідання",
    "lunge": "випад",
    "deadlift": "станова тяга",
    "pullover": "пуловер",
    "kickback": "відведення назад",
    "shrug": "шраг",
    "crunch": "скручування",
    "twist": "поворот",
    "twists": "повороти",
    "plank": "планка",
    "bridge": "місток",
    "stretch": "розтяжка",
    "rotation": "обертання",
    "walk": "ходьба",
    "run": "біг",
    "jump": "стрибок",
    "jumps": "стрибки",
    "clean": "підйом на груди",
    "jerk": "поштовх",
    "snatch": "ривок",
    "thruster": "трастер",
    "windmill": "млин",
    "swing": "мах",
    "carry": "перенесення",
    "climb": "лазіння",
    "crawl": "повзання",
    "bike": "велосипед",
    "elliptical": "еліптичний",
    "ergometer": "ергометр",
    "treadmill": "бігова доріжка",
    "stepmill": "сходовий тренажер",
    "calf": "литкові мʼязи",
    "calves": "литкові мʼязи",
    "hamstring": "задня поверхня стегна",
    "quads": "квадрицепси",
    "glute": "сідничний",
    "glutes": "сідничні мʼязи",
    "triceps": "трицепси",
    "tricep": "трицепс",
    "biceps": "біцепси",
    "bicep": "біцепс",
    "chest": "груди",
    "shoulder": "плече",
    "shoulders": "плечі",
    "delt": "дельта",
    "deltoid": "дельтоподібний мʼяз",
    "lat": "найширший мʼяз спини",
    "lats": "найширші мʼязи спини",
    "back": "спина",
    "neck": "шия",
    "wrist": "запʼясток",
    "hands": "кисті",
    "hand": "кисть",
    "finger": "пальці",
    "forearm": "передпліччя",
    "hip": "стегно",
    "leg": "нога",
    "legs": "ноги",
    "knee": "коліно",
    "knees": "коліна",
    "toe": "носок",
    "feet": "стопи",
    "ankle": "щиколотка",
    "elbow": "лікоть",
    "abdominal": "черевний",
    "oblique": "косий мʼяз живота",
    "core": "мʼязи кора",
    "pelvic": "тазовий",
    "piriformis": "грушоподібний мʼяз",
    "pectoralis major": "великий грудний мʼяз",
    "sternum": "грудина",
    "tibialis": "великогомілковий мʼяз",
    "peroneals": "малогомілкові мʼязи",
    "front": "передній",
    "rear": "задній",
    "side": "бічний",
    "lateral": "латеральний",
    "inner": "внутрішній",
    "outer": "зовнішній",
    "lower": "нижній",
    "upper": "верхній",
    "high": "високий",
    "low": "низький",
    "wide": "широкий",
    "narrow": "вузький",
    "straight": "прямий",
    "bent": "зігнутий",
    "flat": "горизонтальний",
    "incline": "під нахилом",
    "decline": "на похилій лаві вниз",
    "prone": "лежачи обличчям вниз",
    "supine": "лежачи на спині",
    "lying": "лежачи",
    "seated": "сидячи",
    "standing": "стоячи",
    "kneeling": "на колінах",
    "hanging": "у висі",
    "assisted": "з допомогою",
    "weighted": "з обтяженням",
    "reverse": "зворотний",
    "twisting": "з поворотом",
    "squatting": "у присіді",
    "internal": "внутрішній",
    "external": "зовнішній",
    "horizontal": "горизонтальний",
    "vertical": "вертикальний",
    "fixed": "фіксований",
    "through": "через",
    "both": "обидві",
    "down": "вниз",
    "up": "вгору",
    "full": "повний",
    "basic": "базовий",
    "astride": "ноги нарізно",
    "backward": "назад",
    "bicycle": "велосипед",
    "wheel": "колесо",
    "lift": "підйом",
    "towel": "рушник",
    "stance": "стійка",
    "pin": "з упорів",
    "presses": "жими",
    "speed": "швидкісний",
    "rocking": "пружний",
    "battling": "бойові",
    "ropes": "канати",
    "drop": "з падінням",
    "stabilization": "стабілізація",
    "inverse": "зворотний",
    "variation": "варіація",
    "forward": "вперед",
    "pulley": "блок",
    "adduction": "приведення",
    "abduction": "відведення",
    "flip": "переворот",
    "middle": "середній",
    "rotational": "обертальний",
    "pro": "професійний",
    "stirrups": "рукоятки",
    "drive": "тяга",
    "crossover": "кросовер",
    "crossovers": "кросовери",
    "elevated": "піднятий",
    "tuck": "групування",
    "cambered": "вигнутий",
    "chair": "стілець",
    "extended": "витягнутий",
    "tap": "торкання",
    "clap": "плеск",
    "clock": "годинник",
    "crab": "краб",
    "curtsey": "реверанс",
    "cycle": "велосипедний",
    "trainer": "тренажер",
    "deep": "глибокий",
    "alternate": "почерговий",
    "alternating": "почерговий",
    "single": "однією",
    "one": "однією",
    "two": "двома",
    "double": "подвійний",
    "parallel": "паралельний",
    "neutral": "нейтральний",
    "overhead": "над головою",
    "underhand": "зворотним хватом",
    "overhand": "прямим хватом",
    "palms": "долонями",
    "palm": "долонею",
    "grip": "хватом",
    "bend": "нахил",
    "touchers": "торкання",
    "touch": "торкання",
    "squad": "квадрицепсів",
    "circular": "круговий",
    "circles": "обертання",
    "slingers": "лямки",
    "apart": "в сторони",
    "overhead": "над головою",
    "motion": "рух",
    "fours": "четвереньках",
    "pirate": "піратський",
    "supper": "присідання",
    "keens": "коліна",
    "hyght": "високий",
    "sitted": "сидячи",
    "revers": "зворотний",
    "peacher": "Скотта",
    "breeding": "розведення",
    "depresor": "депресор",
    "retractor": "ретрактор",
    "rollerer": "ролер",
    "svend": "Свенд",
    "gironda": "Жиронда",
    "janda": "Джанда",
    "maltese": "мальтійський хрест",
    "planche": "планш",
    "stalder": "Штальдер",
    "otis": "Отіс",
    "cocoons": "кокони",
    "butt-ups": "підйоми тазу",
    "bottoms-up": "знизу вгору",
    "inchworm": "червʼяк",
    "sphinx": "сфінкс",
    "swimmer": "плавець",
    "flutter": "махи",
    "kipping": "кіпінг",
    "cossack": "козацький",
    "sledge": "кувалда",
    "hammer": "молотковий",
    "farmers": "фермерська",
    "skier": "лижник",
    "ski": "лижний",
    "archer": "лучник",
    "judo": "дзюдо",
    "kayak": "каяк",
    "thibaudeau": "Тібодо",
    "cuban": "кубинський",
    "tate": "Тейт",
    "scott": "Скотт",
    "rocky": "Роккі",
    "zercher": "Зерхер",
    "pendlay": "Пендлей",
    "jefferson": "Джефферсон",
    "zottman": "Зоттман",
    "arnold": "Арнольд",
    "behind": "за",
    "head": "головою",
    "floor": "на підлозі",
    "wall": "біля стіни",
    "support": "з опорою",
    "attachment": "насадка",
    "machine": "тренажер",
    "with": "з",
    "without": "без",
    "on": "на",
    "over": "над",
    "against": "біля",
    "between": "між",
    "off": "від",
    "body": "тіло",
    "sit": "сид",
    "kick": "удар",
    "kicks": "удари",
    "tilt": "нахил",
    "reach": "витягування",
    "hang": "вис",
    "bars": "бруси",
    "point": "точка",
    "response": "реакція",
    "slam": "кидок",
    "pose": "поза",
    "hyper": "гіпер",
    "flexor": "згинач",
    "spine": "хребет",
    "straddle": "ноги нарізно",
    "under": "під",
    "to": "до",
    "from": "з",
    "and": "і",
    "in": "у",
    "of": "",
    "the": "",
    "a": "",
    "male": "чоловіки",
    "female": "жінки",
    "back pov": "вид ззаду",
    "side pov": "вид збоку",
}


class TranslationError(RuntimeError):
    pass


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def load_cache(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    data = load_json(path)
    if not isinstance(data, dict):
        raise TranslationError(f"Cache must be a JSON object: {path}")
    return {str(k): str(v) for k, v in data.items()}


def save_cache(path: Path, cache: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, dict(sorted(cache.items())))


def chunked(items: list[str], size: int) -> Iterable[list[str]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def parse_translations(content: str) -> list[str]:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()

    candidates = [text]
    object_match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    array_match = re.search(r"\[.*\]", text, flags=re.DOTALL)
    if object_match:
        candidates.append(object_match.group(0))
    if array_match:
        candidates.append(array_match.group(0))

    last_error: Exception | None = None
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            continue
        if isinstance(parsed, dict):
            parsed = parsed.get("translations", parsed.get("translation"))
        if isinstance(parsed, list) and all(isinstance(item, str) for item in parsed):
            return [cleanup_translation(item) for item in parsed]

    raise TranslationError(f"Could not parse Ollama JSON response: {last_error}\n{text[:1000]}")


def cleanup_translation(text: str) -> str:
    cleaned = " ".join(text.split())
    replacements = {
        "м'яз": "мʼяз",
        "м’яз": "мʼяз",
        "гантелями": "гантелями",
        "гантелью": "гантеллю",
        "(male)": "(чоловіки)",
        "(female)": "(жінки)",
        "(чоловічий)": "(чоловіки)",
        "(жіночий)": "(жінки)",
    }
    for source, target in replacements.items():
        cleaned = cleaned.replace(source, target)
    return cleaned


def rule_based_name_translation(name: str) -> str:
    text = name.lower()
    text = text.replace("в°", "°")
    text = text.replace("_", " ")
    text = re.sub(r"\(([^)]+)\)", r" \1 ", text)
    text = re.sub(r"(?<!\w)v\.\s*(\d+)", r"версія \1", text)
    text = text.replace("°", " градусів")

    for source, target in sorted(NAME_REPLACEMENTS.items(), key=lambda item: len(item[0]), reverse=True):
        text = re.sub(rf"(?<![\w-]){re.escape(source)}(?![\w-])", target, text)

    text = re.sub(r"\s*-\s*", " - ", text)
    text = re.sub(r"\s+", " ", text).strip(" -")
    text = text.replace("  ", " ")
    if not text:
        return name
    return text[0].upper() + text[1:]


def call_ollama(
    names: list[str],
    *,
    model: str,
    ollama_url: str,
    timeout: int,
    num_ctx: int,
) -> list[str]:
    prompt = "Translate this JSON array of exercise names from English to Ukrainian:\n"
    prompt += json.dumps(names, ensure_ascii=False)
    body = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "format": "json",
            "options": {"temperature": 0, "num_ctx": num_ctx},
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        ollama_url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise TranslationError(f"Ollama request failed: {exc}") from exc

    content = payload.get("message", {}).get("content")
    if not isinstance(content, str):
        raise TranslationError(f"Unexpected Ollama payload: {payload!r}")

    translations = parse_translations(content)
    if len(translations) != len(names):
        raise TranslationError(
            f"Expected {len(names)} translations, got {len(translations)}"
        )
    return translations


def translate_batch_with_fallback(
    names: list[str],
    *,
    model: str,
    ollama_url: str,
    timeout: int,
    num_ctx: int,
) -> list[str]:
    try:
        return call_ollama(
            names,
            model=model,
            ollama_url=ollama_url,
            timeout=timeout,
            num_ctx=num_ctx,
        )
    except TranslationError:
        if len(names) <= 1:
            raise
        midpoint = len(names) // 2
        left = translate_batch_with_fallback(
            names[:midpoint],
            model=model,
            ollama_url=ollama_url,
            timeout=timeout,
            num_ctx=num_ctx,
        )
        right = translate_batch_with_fallback(
            names[midpoint:],
            model=model,
            ollama_url=ollama_url,
            timeout=timeout,
            num_ctx=num_ctx,
        )
        return left + right


def unique_names(data: list[dict]) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for item in data:
        name = item.get("name")
        if isinstance(name, str) and name not in seen:
            seen.add(name)
            names.append(name)
    return names


def translate_fixed_value(value: str, translations: dict[str, str], field: str) -> str:
    try:
        return translations[value]
    except KeyError as exc:
        raise TranslationError(f"Missing {field} translation for {value!r}") from exc


def apply_translations(data: list[dict], name_cache: dict[str, str]) -> None:
    for index, item in enumerate(data):
        item["name"] = translate_fixed_value(item["name"], name_cache, "name")
        item["category"] = translate_fixed_value(
            item["category"], CATEGORY_BODY_PART_TRANSLATIONS, "category"
        )
        item["body_part"] = translate_fixed_value(
            item["body_part"], CATEGORY_BODY_PART_TRANSLATIONS, "body_part"
        )
        item["equipment"] = translate_fixed_value(
            item["equipment"], EQUIPMENT_TRANSLATIONS, "equipment"
        )
        item["muscle_group"] = translate_fixed_value(
            item["muscle_group"], MUSCLE_TRANSLATIONS, "muscle_group"
        )
        secondary = item.get("secondary_muscles")
        if not isinstance(secondary, list):
            raise TranslationError(f"secondary_muscles must be a list at record {index}")
        item["secondary_muscles"] = [
            translate_fixed_value(muscle, MUSCLE_TRANSLATIONS, "secondary_muscles")
            for muscle in secondary
        ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "json_path",
        nargs="?",
        default=str(Path(__file__).resolve().parent.parent / "data" / "exercises.json"),
    )
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--ollama-url", default=DEFAULT_OLLAMA_URL)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--num-ctx", type=int, default=16384)
    parser.add_argument("--no-backup", action="store_true")
    parser.add_argument(
        "--rule-based-names",
        action="store_true",
        help="Translate exercise names with the built-in terminology dictionary instead of Ollama.",
    )
    args = parser.parse_args()

    json_path = Path(args.json_path)
    data = load_json(json_path)
    if not isinstance(data, list):
        raise TranslationError("Expected top-level JSON array.")

    names = unique_names(data)
    cache = load_cache(args.cache)
    if args.rule_based_names:
        cache.update({name: rule_based_name_translation(name) for name in names})

    pending = [name for name in names if name not in cache]
    print(f"Records: {len(data)}")
    print(f"Unique names: {len(names)}")
    print(f"Cached names: {len(names) - len(pending)}")
    print(f"Pending names: {len(pending)}")

    translated = 0
    started_at = time.time()
    for batch in chunked(pending, args.batch_size):
        batch_start = time.time()
        translations = translate_batch_with_fallback(
            batch,
            model=args.model,
            ollama_url=args.ollama_url,
            timeout=args.timeout,
            num_ctx=args.num_ctx,
        )
        cache.update(zip(batch, translations, strict=True))
        save_cache(args.cache, cache)
        translated += len(batch)
        elapsed = time.time() - started_at
        print(
            f"Translated {translated}/{len(pending)} pending "
            f"({len(cache)}/{len(names)} total) in {elapsed:.1f}s; "
            f"last batch {time.time() - batch_start:.1f}s",
            flush=True,
        )

    missing = [name for name in names if name not in cache]
    if missing:
        raise TranslationError(f"Missing name translations after run: {len(missing)}")

    if not args.no_backup:
        backup_path = json_path.with_suffix(".before-metadata-uk.json")
        if not backup_path.exists():
            shutil.copy2(json_path, backup_path)
            print(f"Backup saved: {backup_path}")

    apply_translations(data, cache)
    write_json(json_path, data)
    print(f"Updated: {json_path}")
    print("Fields rewritten: name, category, body_part, equipment, muscle_group, secondary_muscles")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
