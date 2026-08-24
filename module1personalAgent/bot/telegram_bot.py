"""
Telegram-бот — вхід для персонального тренера. Слухає повідомлення користувача,
прокидує їх в agent loop (core/agent.py) разом з його особистими даними
(chat_id) і відповідає результатом.

Запуск:
    python -m bot.telegram_bot
"""

import asyncio
import logging

from telegram import Update
from telegram.ext import Application, ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters

from config import BASE_PROMPT, TELEGRAM_BOT_TOKEN
from core.agent import reset_usage, run_agent
from domain import backend

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("personal_trainer_bot")


def handle_query(chat_id: int, text: str) -> dict:
    """Виконується в окремому потоці — run_agent синхронний і блокуючий."""
    backend.set_chat_id(chat_id)
    reset_usage()
    return run_agent(system=BASE_PROMPT, tools=backend.tools(), query=text)


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


def build_app() -> Application:
    if not TELEGRAM_BOT_TOKEN:
        raise SystemExit(
            "Не знайдено TELEGRAM_BOT_TOKEN.\n"
            "  cp .env.example .env   і впишіть токен від @BotFather у .env"
        )
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", on_start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    return app


def main() -> None:
    app = build_app()
    log.info("Бот запущено, чекаю повідомлень...")
    app.run_polling()


if __name__ == "__main__":
    main()
