"""
Порівняння: агент без бази знань і з нею.

    python run.py "Питання"                 # лексичний retriever (11 ручних пунктів)
    python run.py --vector "Питання"         # векторний retriever (увесь текст обох законів)
    python run.py                            # тестове питання за замовчуванням
"""

import sys

from config import BASE_PROMPT
from core.agent import ask

DEFAULT_QUERY = "Мене зупинив поліцейський на дорозі без пояснення причини. Це законно?"


def _retriever(use_vector: bool):
    if use_vector:
        from knowledge_qdrant import as_context, retrieve
    else:
        from domain.knowledge import as_context, retrieve
    return as_context, retrieve


def answer_without_kb(query: str) -> dict:
    return ask(BASE_PROMPT, query)


def answer_with_kb(query: str, as_context, retrieve) -> dict:
    ctx = as_context(query)
    result = ask(BASE_PROMPT + ctx, query)
    result["retrieved"] = len(retrieve(query))
    return result


if __name__ == "__main__":
    args = sys.argv[1:]
    use_vector = "--vector" in args
    args = [a for a in args if a != "--vector"]
    query = " ".join(args) or DEFAULT_QUERY
    as_context, retrieve = _retriever(use_vector)

    backend = "векторний (Qdrant, увесь текст)" if use_vector else "лексичний (11 ручних пунктів)"
    print(f"Питання: «{query}»  [{backend}]\n" + "─" * 70)

    print("\n[Без бази знань — модель відповідає \"з голови\"]")
    r1 = answer_without_kb(query)
    print(r1["answer"])

    print("\n" + "─" * 70)
    print("[З базою знань — RAG]")
    r2 = answer_with_kb(query, as_context, retrieve)
    print(f"(знайдено релевантних пунктів: {r2['retrieved']})")
    print(r2["answer"])
