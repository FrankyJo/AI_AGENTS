"""
База вправ. Детермінований список — джерело правди для агента: він зобов'язаний
брати вправи звідси, а не вигадувати (див. list_exercises у backend.py).

contraindications — теги зон/травм, за яких вправа виключається з видачі
list_exercises. Теги збігаються з тими, що використовує add_constraint:
lower_back, knee, shoulder, neck, wrist, elbow, ankle, hip.
"""

EXERCISES = [
    {"name": "Присідання зі штангою", "muscle_group": "ноги",
     "equipment": ["штанга", "стійки"], "contraindications": ["lower_back", "knee"]},
    {"name": "Гоблет-присід з гантеллю", "muscle_group": "ноги",
     "equipment": ["гантель"], "contraindications": ["knee"]},
    {"name": "Присід у машині Сміта", "muscle_group": "ноги",
     "equipment": ["машина сміта"], "contraindications": ["lower_back"]},
    {"name": "Жим ногами в тренажері", "muscle_group": "ноги",
     "equipment": ["тренажер"], "contraindications": ["knee"]},
    {"name": "Румунська тяга зі штангою", "muscle_group": "ноги",
     "equipment": ["штанга"], "contraindications": ["lower_back"]},
    {"name": "Згинання ніг лежачи в тренажері", "muscle_group": "ноги",
     "equipment": ["тренажер"], "contraindications": []},
    {"name": "Розгинання ніг у тренажері", "muscle_group": "ноги",
     "equipment": ["тренажер"], "contraindications": ["knee"]},
    {"name": "Випади з гантелями", "muscle_group": "ноги",
     "equipment": ["гантелі"], "contraindications": ["knee"]},
    {"name": "Підйом на носки стоячи", "muscle_group": "ноги",
     "equipment": ["тренажер"], "contraindications": ["ankle"]},

    {"name": "Станова тяга класична", "muscle_group": "спина",
     "equipment": ["штанга"], "contraindications": ["lower_back"]},
    {"name": "Тяга штанги в нахилі", "muscle_group": "спина",
     "equipment": ["штанга"], "contraindications": ["lower_back"]},
    {"name": "Тяга верхнього блоку до грудей", "muscle_group": "спина",
     "equipment": ["блочний тренажер"], "contraindications": ["shoulder"]},
    {"name": "Тяга горизонтального блоку", "muscle_group": "спина",
     "equipment": ["блочний тренажер"], "contraindications": ["lower_back"]},
    {"name": "Підтягування", "muscle_group": "спина",
     "equipment": ["турнік"], "contraindications": ["shoulder"]},
    {"name": "Гіперекстензія", "muscle_group": "спина",
     "equipment": ["лава для гіперекстензії"], "contraindications": ["lower_back"]},

    {"name": "Жим штанги лежачи", "muscle_group": "груди",
     "equipment": ["штанга", "лава"], "contraindications": ["shoulder"]},
    {"name": "Жим гантелей на похилій лаві", "muscle_group": "груди",
     "equipment": ["гантелі", "лава"], "contraindications": ["shoulder"]},
    {"name": "Віджимання від підлоги", "muscle_group": "груди",
     "equipment": [], "contraindications": ["wrist", "shoulder"]},
    {"name": "Зведення рук у кросовері", "muscle_group": "груди",
     "equipment": ["кросовер"], "contraindications": ["shoulder"]},

    {"name": "Жим гантелей сидячи", "muscle_group": "плечі",
     "equipment": ["гантелі"], "contraindications": ["shoulder"]},
    {"name": "Махи гантелями в сторони", "muscle_group": "плечі",
     "equipment": ["гантелі"], "contraindications": ["shoulder"]},
    {"name": "Махи гантелями в нахилі (задня дельта)", "muscle_group": "плечі",
     "equipment": ["гантелі"], "contraindications": ["lower_back", "shoulder"]},

    {"name": "Підйом штанги на біцепс", "muscle_group": "руки",
     "equipment": ["штанга"], "contraindications": ["wrist", "elbow"]},
    {"name": "Молотки з гантелями", "muscle_group": "руки",
     "equipment": ["гантелі"], "contraindications": ["elbow"]},
    {"name": "Французький жим з гантеллю", "muscle_group": "руки",
     "equipment": ["гантель"], "contraindications": ["elbow", "shoulder"]},
    {"name": "Віджимання на брусах", "muscle_group": "руки",
     "equipment": ["бруси"], "contraindications": ["shoulder", "elbow"]},
    {"name": "Розгинання рук на блоці", "muscle_group": "руки",
     "equipment": ["блочний тренажер"], "contraindications": ["elbow"]},

    {"name": "Планка", "muscle_group": "кор",
     "equipment": [], "contraindications": ["wrist"]},
    {"name": "Скручування на прес", "muscle_group": "кор",
     "equipment": [], "contraindications": ["lower_back", "neck"]},
    {"name": "Підйом ніг у висі", "muscle_group": "кор",
     "equipment": ["турнік"], "contraindications": ["lower_back", "shoulder"]},
    {"name": "Дроворуб на блоці", "muscle_group": "кор",
     "equipment": ["блочний тренажер"], "contraindications": ["lower_back"]},

    {"name": "Ходьба на біговій доріжці", "muscle_group": "кардіо",
     "equipment": ["доріжка"], "contraindications": ["knee"]},
    {"name": "Велотренажер", "muscle_group": "кардіо",
     "equipment": ["велотренажер"], "contraindications": ["knee"]},
    {"name": "Гребний тренажер", "muscle_group": "кардіо",
     "equipment": ["гребний тренажер"], "contraindications": ["lower_back"]},
    {"name": "Еліптичний тренажер", "muscle_group": "кардіо",
     "equipment": ["еліптичний тренажер"], "contraindications": []},
]
