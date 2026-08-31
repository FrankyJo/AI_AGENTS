"""
Ядро агента.

    ask(system, query)        — один виклик без інструментів: основна відповідь,
                                 а з fast=True — дешевий допоміжний виклик
                                 (LLM-grade, rewrite у self_rag.py)
    run_agent(system, tools, query, dispatch) — цикл «міркуй → дій → спостерігай»
                                 для agentic RAG (rag_agentic.py): модель сама
                                 вирішує, коли й що шукати через search_kb.
"""

import json
import time
from anthropic import Anthropic, APIError, APIStatusError
from config import API_KEY, MODEL, MODEL_FAST, MAX_TOKENS, MAX_TURNS

client = Anthropic(api_key=API_KEY)

USAGE = {"calls": 0, "in": 0, "out": 0}


def reset_usage():
    USAGE.update({"calls": 0, "in": 0, "out": 0})


def _call(**kwargs):
    """Виклик API з ретраями на перевантаження і rate limit."""
    for attempt in range(3):
        try:
            resp = client.messages.create(**kwargs)
            USAGE["calls"] += 1
            USAGE["in"] += resp.usage.input_tokens
            USAGE["out"] += resp.usage.output_tokens
            return resp
        except APIStatusError as e:
            if e.status_code in (429, 500, 529) and attempt < 2:
                time.sleep(2 ** attempt)
                continue
            raise
        except APIError:
            if attempt < 2:
                time.sleep(2 ** attempt)
                continue
            raise


def ask(system: str, query: str, fast: bool = False, max_tokens: int | None = None) -> str | dict:
    """
    fast=False (за замовчуванням) — основна відповідь користувачу: дорога
    модель, повертає dict {"answer", "usage"} — так очікує run.py.

    fast=True — допоміжний виклик (grade/rewrite у self_rag.py): дешева
    модель, повертає просто рядок відповіді.

    Примітка: класичний sampling-параметр temperature у поточній версії
    SDK (anthropic 1.2.0) прибрано з messages.create() — новіші моделі
    керуються інакше (effort), тому тут його немає.
    """
    resp = _call(model=MODEL_FAST if fast else MODEL,
                 max_tokens=max_tokens or (60 if fast else MAX_TOKENS),
                 system=system,
                 messages=[{"role": "user", "content": query}])
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    if fast:
        return text
    return {"answer": text,
            "usage": {"input_tokens": resp.usage.input_tokens,
                      "output_tokens": resp.usage.output_tokens}}


def run_agent(system: str, tools: list, query: str, dispatch, on_step=None) -> dict:
    """
    Цикл «міркуй → дій → спостерігай» — потрібен, лише коли в агента є
    інструменти (search_kb в rag_agentic.py). dispatch(name, args) -> dict
    виконує виклик і повертає результат для моделі.
    """
    messages = [{"role": "user", "content": query}]
    trace = []

    for turn in range(MAX_TURNS):
        kwargs = dict(model=MODEL, max_tokens=MAX_TOKENS, system=system, messages=messages)
        if tools:
            kwargs["tools"] = tools

        try:
            resp = _call(**kwargs)
        except Exception as e:
            return {"answer": "Сервіс тимчасово недоступний. Спробуйте пізніше.",
                    "outcome": "api_error", "error": f"{type(e).__name__}: {e}",
                    "trace": trace, "turns": turn}

        tool_uses = [b for b in resp.content if b.type == "tool_use"]

        if resp.stop_reason != "tool_use":                     # фінальна відповідь
            text = "".join(b.text for b in resp.content if b.type == "text")
            return {"answer": text.strip(), "outcome": "ok", "trace": trace, "turns": turn + 1}

        results = []
        for tu in tool_uses:
            output = dispatch(tu.name, tu.input)
            step = {"turn": turn, "tool": tu.name, "input": tu.input, "output": output}
            trace.append(step)
            if on_step:
                on_step(step)
            results.append({"type": "tool_result", "tool_use_id": tu.id,
                            "content": json.dumps(output, ensure_ascii=False)})

        messages.append({"role": "assistant", "content": resp.content})
        messages.append({"role": "user", "content": results})

    return {"answer": "Не вдалося завершити обробку за відведену кількість кроків.",
            "outcome": "turns_exhausted", "trace": trace, "turns": MAX_TURNS}
