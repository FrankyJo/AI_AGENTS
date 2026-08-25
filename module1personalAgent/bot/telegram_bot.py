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
import pathlib

from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update, WebAppInfo
from telegram.ext import Application, ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters

from config import BASE_PROMPT, BOT_NAME, PUBLIC_BASE_URL, TELEGRAM_BOT_TOKEN
from core import cost
from core.agent import USAGE, reset_usage, run_agent, summarize_into_notes
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


def handle_query(chat_id: int, text: str, use_history: bool = True) -> dict:
    """Виконується в окремому потоці — run_agent синхронний і блокуючий.

    use_history=False — для системних тригерів (нагадування), щоб їхній
    службовий текст не потрапляв у діалог як нібито сказане користувачем."""
    backend.set_chat_id(chat_id)
    reset_usage()

    system = BASE_PROMPT
    history = None
    if use_history:
        history = backend.get_conversation()
        notes = backend.get_memory_notes()
        if notes:
            system = f"{BASE_PROMPT}\n\nДовгострокові нотатки про користувача:\n{notes}"

    result = run_agent(system=system, tools=backend.tools(), query=text, history=history)

    if use_history:
        dropped = backend.append_conversation(text, result["answer"])
        if dropped:
            # рахуємо ДО usage_log.append — інакше вартість сумаризації "втече"
            # у лог наступного, ніяк не пов'язаного повідомлення
            notes = summarize_into_notes(backend.get_memory_notes(), dropped)
            backend.update_memory_notes(notes)

    usage_log.append(chat_id, dict(USAGE["by_model"]))
    return result


async def on_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        f"Привіт! Я {BOT_NAME}, твій особистий тренер. Як тебе звати і як до "
        "тебе звертатися?\n\n"
        "Далі розкажи, чим займаєшся і яка в тебе програма, і обов'язково "
        "згадай, якщо щось болить або є обмеження — я це запам'ятаю і буду "
        "враховувати при підборі вправ.\n\n"
        "Усі команди — /info."
    )


INFO_TEXT_TEMPLATE = (
    "Я {name} — персональний фітнес-тренер зі штучним інтелектом.\n\n"
    "Команди:\n"
    "/start — коротке привітання\n"
    "/dashboard — відкрити прогрес, профіль і програму (графіки)\n"
    "/usage — скільки токенів і $ ти витратив на бота: сьогодні / 7 днів / 30 днів\n"
    "/info — цей список команд\n\n"
    "Крім команд, просто пиши мені звичайним текстом: розказуй про тренування, "
    "болі, вагу і повтори в підходах, проси скласти чи змінити програму — я все "
    "запам'ятовую і веду облік прогресу."
)


async def on_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(INFO_TEXT_TEMPLATE.format(name=BOT_NAME))


async def _send_exercise_gifs(update: Update, trace: list) -> None:
    """Агент цикл текстовий (не може сам прикріпити зображення) — тому після
    відповіді окремо надсилаємо гіфку для кожної вправи, яку він щойно
    подивився через get_exercise_details."""
    sent = set()
    for step in trace:
        if step["tool"] != "get_exercise_details" or step.get("failed"):
            continue
        output = step["output"]
        gif_path = output.get("gif_path")
        if not gif_path or gif_path in sent or not pathlib.Path(gif_path).exists():
            continue
        sent.add(gif_path)
        with open(gif_path, "rb") as f:
            await update.message.reply_animation(f, caption=output.get("name"))


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    text = update.message.text
    result = await asyncio.to_thread(handle_query, chat_id, text)

    if result["outcome"] != "ok":
        log.warning("outcome=%s chat_id=%s query=%r", result["outcome"], chat_id, text)

    await update.message.reply_text(result["answer"])
    await _send_exercise_gifs(update, result.get("trace", []))


async def on_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not PUBLIC_BASE_URL:
        await update.message.reply_text(
            "Дашборд ще не налаштовано: не задано PUBLIC_BASE_URL у .env "
            "(HTTPS-адреса webapp/server.py, наприклад публічний URL від ngrok)."
        )
        return
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("📊 Відкрити прогрес", web_app=WebAppInfo(url=PUBLIC_BASE_URL))
    ]])
    await update.message.reply_text("Тисни, щоб відкрити свій прогрес:", reply_markup=keyboard)


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
            result = await asyncio.to_thread(handle_query, chat_id, CHECK_IN_TRIGGER, False)
            await context.bot.send_message(chat_id=int(chat_id), text=result["answer"])
        except Exception:
            log.exception("не вдалося надіслати нагадування chat_id=%s", chat_id)
        finally:
            backend.set_chat_id(chat_id)
            backend.mark_check_in_sent()


async def _post_init(app: Application) -> None:
    """Реєструє команди в меню Telegram (список за '/' у клієнті)."""
    await app.bot.set_my_commands([
        BotCommand("start", "Почати спочатку"),
        BotCommand("dashboard", "Прогрес, профіль і програма"),
        BotCommand("usage", "Скільки витрачено на бота"),
        BotCommand("info", "Список усіх команд"),
    ])


def build_app() -> Application:
    if not TELEGRAM_BOT_TOKEN:
        raise SystemExit(
            "Не знайдено TELEGRAM_BOT_TOKEN.\n"
            "  cp .env.example .env   і впишіть токен від @BotFather у .env"
        )
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).post_init(_post_init).build()
    app.add_handler(CommandHandler("start", on_start))
    app.add_handler(CommandHandler("usage", on_usage))
    app.add_handler(CommandHandler("dashboard", on_dashboard))
    app.add_handler(CommandHandler("info", on_info))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    app.job_queue.run_daily(send_body_metrics_check_ins, time=datetime.time(hour=10, minute=0))
    return app


def main() -> None:
    app = build_app()
    log.info("Бот запущено, чекаю повідомлень...")
    app.run_polling()


if __name__ == "__main__":
    main()
