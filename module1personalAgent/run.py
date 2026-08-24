"""
Тестовий прогін агента без Telegram — для налагодження.

    python run.py "У мене програма: присід, жим лежачи, тяга. Болить поперек."
    python run.py                      # запит за замовчуванням
"""

import sys

from config import BASE_PROMPT
from core import cost
from core.agent import USAGE, reset_usage, run_agent
from domain import backend

CHAT_ID = "cli-test"

DEFAULT_QUERY = (
    "Привіт, хочу почати тренуватися. Склади мені програму на 3 дні в залі, "
    "мета — набір маси. З обладнання є штанга, гантелі й тренажери."
)


def main() -> None:
    query = " ".join(sys.argv[1:]) or DEFAULT_QUERY
    backend.set_chat_id(CHAT_ID)
    reset_usage()

    result = run_agent(system=BASE_PROMPT, tools=backend.tools(), query=query)

    print(f"Запит: {query}\n{'-' * 70}")
    print(result["answer"])
    print("-" * 70)
    tools_used = [t["tool"] for t in result.get("trace", [])]
    print(f"інструменти: {' → '.join(tools_used) if tools_used else 'не викликались'}")
    print(f"результат: {result['outcome']}")
    if result.get("failures"):
        print(f"збоїв інструментів: {len(result['failures'])}")
    print(f"вартість: ${cost.usd(USAGE['by_model']):.5f} за {USAGE['calls']} викликів "
          f"({USAGE['in']}→{USAGE['out']} токенів)")


if __name__ == "__main__":
    main()
