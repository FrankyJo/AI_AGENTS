"""
Agentic RAG: пошук стає інструментом.

Static RAG (run.py, self_rag.py): один пошук на весь запит, до відповіді.
Agentic RAG: модель сама вирішує, КОЛИ і ЩО шукати, і може зробити кілька
різних пошуків за один діалог — корисно на складених питаннях («яка
швидкість ТА чи можна без ременя» — це два різні пошуки).

    python rag_agentic.py                 # тестове складене питання
    python rag_agentic.py "своє питання"
"""

import sys

from config import BASE_PROMPT
from core.agent import run_agent
from knowledge_qdrant import retrieve

TEST_QUERY = (
    "Яка максимальна швидкість у місті і чи можу я не пристібати пасажира "
    "ззаду, якщо в машині немає ременів безпеки на задньому сидінні?"
)


def _search_kb(query: str) -> dict:
    hits = retrieve(query, k=6)
    return {"laws": hits} if hits else {"laws": [], "note": "нічого не знайдено"}


SEARCH_KB_SCHEMA = {
    "name": "search_kb",
    "description": "Шукає в проіндексованих законах і кодексах України за смисловим запитом. "
                   "Викликай перед будь-яким твердженням про норму закону — не покладайся "
                   "на память. Для складеного питання роби окремий пошук на кожен аспект.",
    "input_schema": {
        "type": "object",
        "properties": {"query": {"type": "string",
                                 "description": "Пошуковий запит, напр. «швидкість у населеному пункті»"}},
        "required": ["query"],
    },
}

TOOLS_IMPL = {"search_kb": _search_kb}


def _dispatch(name: str, args: dict) -> dict:
    fn = TOOLS_IMPL.get(name)
    if not fn:
        return {"error": f"unknown_tool:{name}"}
    try:
        return fn(**args)
    except TypeError as e:
        return {"error": f"bad_args: {e}"}


def run_agentic(query: str) -> dict:
    result = run_agent(
        system=BASE_PROMPT + " Норми закону бери ТІЛЬКИ з search_kb — не вигадуй.",
        tools=[SEARCH_KB_SCHEMA],
        query=query,
        dispatch=_dispatch,
    )
    result["kb_searches"] = [t["input"].get("query") for t in result["trace"]
                             if t["tool"] == "search_kb"]
    return result


if __name__ == "__main__":
    query = " ".join(sys.argv[1:]) or TEST_QUERY
    print(f"Питання: «{query}»\n" + "─" * 70)
    r = run_agentic(query)
    print(f"пошуки агента: {r['kb_searches']}")
    print(f"\n{r['answer']}")
