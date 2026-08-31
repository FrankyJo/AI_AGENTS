"""
Self-RAG / CRAG: ворота між пошуком і відповіддю.

Порядок (від дешевого до дорогого):
  1. ПОРІГ — вже вбудований у knowledge_qdrant.retrieve() (score_threshold,
     fail-closed): зовсім нерелевантне відсіюється безкоштовно.
  2. LLM-GRADE — поріг міг пропустити витяг, який формально схожий, але не
     відповідає на питання по суті. Питаємо дешеву модель: RELEVANT чи WEAK.
  3. WEAK → CRAG-крок: переформулювати запит мовою закону і шукати ще раз.
  4. Якщо й після rewrite нічого путнього — чесна відмова замість вигадки.

    python self_rag.py                # три тестові питання
    python self_rag.py "своє питання"
"""

import sys

from config import BASE_PROMPT
from core.agent import ask
from knowledge_qdrant import retrieve

GRADE = (
    "Ти — воротар RAG-системи з юридичних питань України. Дано витяг "
    "із законів і питання клієнта. Оціни, чи ДОСТАТНЬО цього витягу, щоб "
    "відповісти по суті питання.\nВідповідай одним словом: RELEVANT або WEAK."
)
REWRITE = (
    "Переформулюй запит користувача в 3-7 слів мовою українського "
    "законодавства: точні юридичні терміни замість побутових виразів "
    "(напр. «зупинення транспортного засобу» замість «зупинили на дорозі», "
    "«позовна давність» замість «скільки часу є на позов»). "
    "Поверни лише переформульований запит."
)
ESCALATION = (
    "На жаль, у проіндексованих джерелах я не знайшов відповіді на це "
    "питання навіть після переформулювання запиту. Радимо звернутися до "
    "практикуючого юриста або перевірити актуальну редакцію потрібного "
    "закону на zakon.rada.gov.ua.\n\nЦе навчальний прототип, а не офіційна "
    "юридична консультація."
)

QUERIES = [
    "Мене зупинив поліцейський на дорозі без пояснення причини. Це законно?",
    "Патрульний тормознув мене на трасі, каже перевірка документів — на якій підставі?",
    "Скільки коштує проїзд у міжміському автобусі?",
]


def grade(ctx: list[str], query: str) -> str:
    """Ворота. RELEVANT або WEAK."""
    if not ctx:
        return "WEAK"                     # поріг уже все відсіяв — питати нема про що
    verdict = ask(GRADE, f"Питання: {query}\n\nВитяг законів:\n" + "\n".join(ctx), fast=True)
    return "WEAK" if "WEAK" in verdict.upper() else "RELEVANT"


def answer_with_gate(query: str, k: int = 6) -> dict:
    trace = []
    ctx = retrieve(query, k)
    trace.append(f"retrieve → {len(ctx)} витягів")

    verdict = grade(ctx, query)
    trace.append(f"grade → {verdict}")

    if verdict == "WEAK":
        better = ask(REWRITE, query, fast=True)          # CRAG: переформулювати і шукати ще раз
        ctx2 = retrieve(better, k)
        trace.append(f"rewrite → «{better}» → {len(ctx2)} витягів")
        if ctx2 and grade(ctx2, query) == "RELEVANT":
            ctx, verdict = ctx2, "RELEVANT (після rewrite)"
        else:
            trace.append("ескалація → людині")
            return {"answer": ESCALATION, "verdict": "WEAK", "trace": trace,
                    "escalated": True, "contexts": ctx2}

    context_block = "\n\nВитяг з бази знань:\n" + "\n---\n".join(ctx)
    result = ask(BASE_PROMPT + context_block, query)
    result.update(verdict=verdict, trace=trace, escalated=False, retrieved=len(ctx), contexts=ctx)
    return result


if __name__ == "__main__":
    args = sys.argv[1:]
    queries = [" ".join(args)] if args else QUERIES
    for q in queries:
        r = answer_with_gate(q)
        print(f"\n«{q}»")
        for step in r["trace"]:
            print(f"   {step}")
        print(f"   → {r['answer'][:250]}")
    if not args:
        print("\n" + "=" * 70)
        print("Пуант: жодного разу агент не вигадав статтю. Або знайшов, або")
        print("переформулював і знайшов, або чесно віддав людині.")
