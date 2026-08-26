"""
Ядро: клієнт API + agent loop.

Цей файл не прив'язаний до фітнес-домену — доменні інструменти приходять ззовні
через `tools`, а виклик конкретного інструмента йде через `domain.backend.dispatch`.
Явно обробляються п'ять результатів: ok · tool_error · turns_exhausted · api_error ·
no_tool_used · budget_exceeded.
"""

import datetime
import json
import time
from anthropic import Anthropic, APIError, APIStatusError
from config import API_KEY, MODEL, MODEL_FAST, MAX_TOKENS, MAX_TURNS, MAX_COST_USD
from core import cost

client = Anthropic(api_key=API_KEY)

# накопичувач вартості прогону
USAGE = {"calls": 0, "in": 0, "out": 0, "cache_write": 0, "cache_read": 0, "by_model": {}}


def _usage_dict(usage) -> dict:
    """Anthropic Usage-об'єкт -> плоский словник, разом з токенами
    prompt-кешування (без них /usage занижував би вартість, бо кеш-запис і
    кеш-читання рахуються за іншою ціною, ніж звичайний input)."""
    return {"calls": 1, "in": usage.input_tokens, "out": usage.output_tokens,
            "cache_write": getattr(usage, "cache_creation_input_tokens", 0) or 0,
            "cache_read": getattr(usage, "cache_read_input_tokens", 0) or 0}


def _track(model, usage):
    u = _usage_dict(usage)
    USAGE["calls"] += 1
    USAGE["in"] += u["in"]
    USAGE["out"] += u["out"]
    USAGE["cache_write"] += u["cache_write"]
    USAGE["cache_read"] += u["cache_read"]
    m = USAGE["by_model"].setdefault(model, {"calls": 0, "in": 0, "out": 0, "cache_write": 0, "cache_read": 0})
    m["calls"] += 1
    m["in"] += u["in"]
    m["out"] += u["out"]
    m["cache_write"] += u["cache_write"]
    m["cache_read"] += u["cache_read"]


def reset_usage():
    USAGE.update({"calls": 0, "in": 0, "out": 0, "cache_write": 0, "cache_read": 0, "by_model": {}})


def _call(**kwargs):
    """Виклик API з ретраями на перевантаження і rate limit."""
    for attempt in range(3):
        try:
            resp = client.messages.create(**kwargs)
            _track(kwargs["model"], resp.usage)
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


def run_agent(system: str, tools: list, query: str, history: list = None,
              context: str = None, on_step=None) -> dict:
    """
    Цикл «міркуй → дій → спостерігай».

    history — попередні репліки діалогу (лише видимий текст user/assistant,
    без внутрішніх tool_use/tool_result одного запиту — інакше контекст ріс
    би необмежено). Викликач сам вирішує, скільки зберігати і чи зберігати
    взагалі (див. domain.backend.get_conversation/append_conversation).

    context — динамічний текст про конкретного користувача (напр.
    memory_notes), який НЕ йде в system. system лишається дослівно тим самим
    рядком для геть усіх користувачів і запитів — навмисно, щоб Anthropic
    prompt caching міг перевикористовувати незмінний префікс (system+tools,
    основна маса вартості запиту) замість оплати його щоразу заново. Якби
    персональні нотатки чи дата приклеювались до system, кожен користувач
    зривав би кеш для самого себе. Тому дата й context ідуть у перше
    повідомлення, а не в system.

    Повертає, окрім відповіді:
      outcome      — ok | turns_exhausted | api_error | budget_exceeded
      failures     — перелік збоїв інструментів
      no_tool_used — модель відповіла, жодного разу не звернувшись до бекенду
    """
    from domain.backend import dispatch

    system_blocks = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]

    # модель не знає поточної дати сама — без цього вона вгадує рік при
    # log_workout/log_set і може записати тренування під неправильною датою
    context_lines = [f"[КОНТЕКСТ] Сьогоднішня дата: {datetime.date.today().isoformat()}."]
    if context:
        context_lines.append(f"Довгострокові нотатки про користувача:\n{context}")
    query_with_context = "\n".join(context_lines) + f"\n\n{query}"

    cached_tools = None
    if tools:
        cached_tools = list(tools)
        cached_tools[-1] = {**cached_tools[-1], "cache_control": {"type": "ephemeral"}}

    messages = list(history or []) + [{"role": "user", "content": query_with_context}]
    trace, failures = [], []
    spent_usd = 0.0
    started = time.time()

    for turn in range(MAX_TURNS):
        kwargs = dict(model=MODEL, max_tokens=MAX_TOKENS, system=system_blocks, messages=messages)
        if cached_tools:
            kwargs["tools"] = cached_tools

        try:
            resp = _call(**kwargs)
        except Exception as e:                                    # ← збій API
            return {"answer": "Сервіс тимчасово недоступний, спробуй ще раз трохи пізніше.",
                    "outcome": "api_error", "error": f"{type(e).__name__}: {e}",
                    "trace": trace, "failures": failures, "turns": turn,
                    "elapsed_sec": round(time.time() - started, 2), "usage": {}}

        tool_uses = [b for b in resp.content if b.type == "tool_use"]

        if resp.stop_reason != "tool_use":                        # ← фінальна відповідь
            text = "".join(b.text for b in resp.content if b.type == "text")
            return {"answer": text.strip(), "outcome": "ok",
                    "trace": trace, "failures": failures, "turns": turn + 1,
                    "no_tool_used": len(trace) == 0,
                    "elapsed_sec": round(time.time() - started, 2),
                    "usage": {"input_tokens": resp.usage.input_tokens,
                              "output_tokens": resp.usage.output_tokens}}

        spent_usd += cost.usd({MODEL: _usage_dict(resp.usage)})
        if spent_usd > MAX_COST_USD:                               # ← бюджет вичерпано
            return {"answer": f"Досягнуто ліміту вартості обробки (${MAX_COST_USD:.2f}). "
                              "Спробуй сформулювати запит коротше або напиши ще раз.",
                    "outcome": "budget_exceeded", "trace": trace, "failures": failures,
                    "turns": turn + 1, "spent_usd": round(spent_usd, 6),
                    "elapsed_sec": round(time.time() - started, 2), "usage": {}}

        results = []
        for tu in tool_uses:
            output = dispatch(tu.name, tu.input)
            step = {"turn": turn, "tool": tu.name, "input": tu.input, "output": output}
            if "error" in output:                                 # ← збій інструмента
                step["failed"] = True
                failures.append({"tool": tu.name, "error": output["error"]})
            trace.append(step)
            if on_step:
                on_step(step)
            results.append({"type": "tool_result", "tool_use_id": tu.id,
                            "content": json.dumps(output, ensure_ascii=False),
                            "is_error": "error" in output})

        messages.append({"role": "assistant", "content": resp.content})
        messages.append({"role": "user", "content": results})

    # ← ліміт кроків вичерпано
    return {"answer": "Не вдалося завершити обробку за відведену кількість кроків. "
                      "Спробуй розбити запит на частини.",
            "outcome": "turns_exhausted", "trace": trace, "failures": failures,
            "turns": MAX_TURNS, "elapsed_sec": round(time.time() - started, 2), "usage": {}}


def summarize_into_notes(existing_notes: str, dropped_turns: list) -> str:
    """Стискає репліки, що випадають з вікна історії (див.
    domain.backend.append_conversation), у компактні довгострокові нотатки —
    без цього старий контекст просто зникав би безслідно. Швидка/дешева
    модель, бо це фонова бухгалтерія, а не основний діалог."""
    if not dropped_turns:
        return existing_notes

    dialogue = "\n".join(f"{t['role']}: {t['content']}" for t in dropped_turns)
    prompt = (
        "Онови короткі нотатки про користувача новою реплікою діалогу, що "
        "випадає з короткострокової історії. Залиш лише те, що варто "
        "пам'ятати надовго (факти, вподобання, плани, важливі деталі) — не "
        "механічний переказ реплік.\n\n"
        f"Поточні нотатки:\n{existing_notes or '(порожньо)'}\n\n"
        f"Нова репліка:\n{dialogue}\n\n"
        "Оновлені нотатки (стисло, кілька речень):"
    )
    resp = _call(model=MODEL_FAST, max_tokens=300, messages=[{"role": "user", "content": prompt}])
    return "".join(b.text for b in resp.content if b.type == "text").strip()
