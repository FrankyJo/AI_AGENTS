"""
Роутер: дешевий класифікатор перед вибором конвеєра.

Просте питання (один аспект — «яка швидкість дозволена») → self_rag.py:
1-2 виклики моделі, швидко. Складене (кілька різних аспектів одночасно —
«яка швидкість І чи законна відмова показати докази») → rag_agentic.py:
модель сама шукає стільки разів, скільки треба, дорожче й повільніше,
але не губить частину питання (README, розділ «Реальний кейс»).

Підстраховка: якщо класифікатор помилився (визначив як просте, а
self_rag усе одно ескалював) — не віддаємо людині чесну відмову одразу,
а пробуємо agentic як останню спробу. Гірший випадок дорожчий (класифікація
+ невдала спроба self_rag + повний agentic), але рідкісний — і краще
заплатити зайвий виклик, ніж помилково відмовити на питанні, яке агент
насправді міг закрити.

    python router.py "своє питання"
"""

import sys

from core.agent import ask
from rag_agentic import run_agentic
from self_rag import answer_with_gate

CLASSIFY = (
    "Юридичне питання користувача — ПРОСТЕ (стосується одного аспекту чи "
    "однієї норми) чи СКЛАДЕНЕ (просить одразу кілька різних речей — "
    "наприклад ліміт швидкості, і вимоги до доказів, і права водія, і "
    "порядок оскарження одночасно)? Відповідай одним словом: ПРОСТЕ або "
    "СКЛАДЕНЕ."
)


def is_compound(query: str) -> bool:
    verdict = ask(CLASSIFY, query, fast=True)
    return "СКЛАДЕНЕ" in verdict.upper()


def answer(query: str) -> dict:
    if is_compound(query):
        result = run_agentic(query)
        result["pipeline"] = "agentic (класифіковано як складене)"
        return result

    result = answer_with_gate(query)
    if result.get("escalated"):
        fallback = run_agentic(query)
        fallback["pipeline"] = "agentic (fallback — self_rag ескалював)"
        return fallback

    result["pipeline"] = "self_rag (класифіковано як просте)"
    return result


if __name__ == "__main__":
    q = " ".join(sys.argv[1:]) or "Яка дозволена швидкість руху у населеному пункті?"
    print(f"Питання: «{q}»\n" + "─" * 70)
    compound = is_compound(q)
    print(f"класифікація: {'СКЛАДЕНЕ' if compound else 'ПРОСТЕ'}")
    r = answer(q)
    print(f"конвеєр: {r['pipeline']}")
    print(f"\n{r['answer']}")
