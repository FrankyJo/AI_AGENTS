"""
Telegram-бот — вхід для персонального тренера. Слухає повідомлення користувача,
прокидує їх в agent loop (core/agent.py) разом з його особистими даними
(chat_id) і відповідає результатом.

Запуск:
    python -m bot.telegram_bot
"""

import asyncio
import datetime
import logging

from telegram import Update
from telegram.ext import Application, ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters

from config import BASE_PROMPT, TELEGRAM_BOT_TOKEN
from core import cost
from core.agent import USAGE, reset_usage, run_agent
from domain import backend
from storage import usage_log

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("personal_trainer_bot")

CHECK_IN_TRIGGER = (
    "[СИСТЕМНЕ НАГАДУВАННЯ, не повідомлення від користувача] Настав час "
    "планового нагадування (раз на 1-2 тижні) — попроси користувача коротко "
    "надіслати поточну вагу тіла й основні обхвати (ноги, руки, талія тощо), "
    "щоб відстежувати зміни тіла з часом. Просто напиши коротке дружнє "
    "повідомлення від себе, інструменти для цього викликати не потрібно."
)


def handle_query(chat_id: int, text: str) -> dict:
    """Виконується в окремому потоці — run_agent синхронний і блокуючий."""
    backend.set_chat_id(chat_id)
    reset_usage()
    result = run_agent(system=BASE_PROMPT, tools=backend.tools(), query=text)
    usage_log.append(chat_id, dict(USAGE["by_model"]))
    return result


async def on_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Привіт! Я твій особистий тренер. Розкажи, чим займаєшся і яка в тебе "
        "програма, і обов'язково згадай, якщо щось болить або є обмеження — "
        "я це запам'ятаю і буду враховувати при підборі вправ."
    )


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    text = update.message.text
    result = await asyncio.to_thread(handle_query, chat_id, text)

    if result["outcome"] != "ok":
        log.warning("outcome=%s chat_id=%s query=%r", result["outcome"], chat_id, text)

    await update.message.reply_text(result["answer"])


def _usage_section(title: str, records: list, cutoff: datetime.datetime) -> str:
    period = [r for r in records if datetime.datetime.fromisoformat(r["ts"]) >= cutoff]
    by_model = cost.aggregate(period)
    if not by_model:
        return f"{title}: викликів не було"
    rows = "\n".join(
        f"  {row['model']}: {row['calls']} викликів, {row['in']}→{row['out']} токенів, ${row['usd']:.4f}"
        for row in cost.breakdown(by_model))
    return f"{title}: ${cost.usd(by_model):.4f}\n{rows}"


async def on_usage(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    records = usage_log.for_chat(update.effective_chat.id)
    now = datetime.datetime.now()
    today_start = datetime.datetime.combine(now.date(), datetime.time.min)

    text = "Твої витрати на цього бота:\n\n" + "\n\n".join([
        _usage_section("Сьогодні", records, today_start),
        _usage_section("Останні 7 днів", records, now - datetime.timedelta(days=7)),
        _usage_section("Останні 30 днів", records, now - datetime.timedelta(days=30)),
    ])
    await update.message.reply_text(text)


async def send_body_metrics_check_ins(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Раз на добу перевіряє всіх відомих користувачів і шле нагадування тим,
    у кого настав чи минув термін (кожен окремий термін — раз на 1-2 тижні,
    врозкид — див. domain.backend.CHECK_IN_MIN_DAYS/MAX_DAYS)."""
    for chat_id in backend.list_known_chat_ids():
        if not chat_id.lstrip("-").isdigit():          # напр. "cli-test" з run.py — не Telegram-чат
            continue
        backend.set_chat_id(chat_id)
        if not backend.is_check_in_due():
            continue
        try:
            result = await asyncio.to_thread(handle_query, chat_id, CHECK_IN_TRIGGER)
            await context.bot.send_message(chat_id=int(chat_id), text=result["answer"])
        except Exception:
            log.exception("не вдалося надіслати нагадування chat_id=%s", chat_id)
        finally:
            backend.set_chat_id(chat_id)
            backend.mark_check_in_sent()


def build_app() -> Application:
    if not TELEGRAM_BOT_TOKEN:
        raise SystemExit(
            "Не знайдено TELEGRAM_BOT_TOKEN.\n"
            "  cp .env.example .env   і впишіть токен від @BotFather у .env"
        )
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", on_start))
    app.add_handler(CommandHandler("usage", on_usage))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    app.job_queue.run_daily(send_body_metrics_check_ins, time=datetime.time(hour=10, minute=0))
    return app


def main() -> None:
    app = build_app()
    log.info("Бот запущено, чекаю повідомлень...")
    app.run_polling()


if __name__ == "__main__":
    main()
