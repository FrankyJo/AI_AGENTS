"""
Telegram-бот поверх agentic RAG (rag_agentic.run_agentic).

    python bot.py

Long polling — не потрібен публічний HTTPS-сервер, достатньо запустити
процес там, де є мережа (свій ноутбук, VPS, контейнер). Якщо бот піде в
продакшн з великим навантаженням — тоді має сенс перейти на webhook, але
для навчального прототипу polling простіший і достатній.

Було: self_rag.answer_with_gate() — один retrieval (+ один rewrite на
WEAK). Дешевше, але на складених питаннях (кілька різних аспектів в
одному запиті) губиться й ескалює людині, хоча потрібні норми є в базі
— просто жоден одиничний пошук не піднімає їх усі разом (реальний кейс —
README, розділ «Реальний кейс: чому self_rag ескалює, а agentic — ні»).

Зараз: router.answer() — дешевий класифікатор (просте/складене питання)
вирішує, куди йти: просте → self_rag (1-2 виклики моделі, швидко),
складене → одразу agentic (модель сама шукає, скільки треба). Якщо
класифікатор помилився і self_rag усе одно ескалював — остання спроба
через agentic перш ніж чесно відмовляти (router.py).

Синхронний виклик router.answer() виконується в окремому потоці через
run_in_executor, щоб не блокувати asyncio event loop бота. На складеному
питанні (кілька послідовних викликів моделі, кожен пошук — окремий turn)
відповідь може займати 5-30+ секунд — індикатор "друкує..." оновлюється
кожні 4с окремою задачею (`_keep_typing`), інакше Telegram гасить його
вже через ~5с.
"""

import asyncio
import datetime
import logging

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from config import ADMIN_CHAT_ID, TELEGRAM_BOT_TOKEN
from core import cost
from core.agent import USAGE
from router import answer as route_answer
from watch import check_for_updates

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)     # придушити шумні debug-логи бібліотек
logging.getLogger("sentence_transformers").setLevel(logging.WARNING)
log = logging.getLogger("lawyer_bot")

START_TIME = datetime.datetime.now()    # для /usage — "з моменту запуску процесу"

WELCOME = (
    "Вітаю! Я консультую з питань права України — спираючись лише на "
    "текст проіндексованих законів і кодексів, а не на власні здогадки.\n\n"
    "Постав питання звичайним повідомленням, наприклад:\n"
    "«Мене зупинив поліцейський без пояснення причини, це законно?»\n\n"
    "Це навчальний прототип, а не офіційна юридична консультація."
)
TELEGRAM_LIMIT = 4000    # трохи менше за ліміт Telegram (4096) — про запас


def _split_for_telegram(text: str) -> list[str]:
    """Ріже по абзацах (порожній рядок між ними), не посеред слова чи
    речення — на відміну від сліпого answer[i:i+LIMIT]. Абзац, довший за
    ліміт сам по собі (рідкість — модель зазвичай не пише такого суцільним
    блоком), доводиться різати жорстко, інакше застрягне назавжди."""
    chunks = []
    current = ""
    for para in text.split("\n\n"):
        candidate = f"{current}\n\n{para}" if current else para
        if len(candidate) <= TELEGRAM_LIMIT:
            current = candidate
            continue
        if current:
            chunks.append(current)
        if len(para) <= TELEGRAM_LIMIT:
            current = para
        else:
            for i in range(0, len(para), TELEGRAM_LIMIT):
                chunks.append(para[i:i + TELEGRAM_LIMIT])
            current = ""
    if current:
        chunks.append(current)
    return chunks or [text]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(WELCOME)


async def _keep_typing(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    """Telegram гасить "друкує..." вже за ~5с — agentic-відповідь із
    кількома пошуками часто довша, тому оновлюємо, поки триває обробка."""
    try:
        while True:
            await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
            await asyncio.sleep(4)
    except asyncio.CancelledError:
        pass


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.message.text
    chat_id = update.effective_chat.id
    log.info("chat=%s питання=%r", chat_id, query[:120])

    typing_task = asyncio.create_task(_keep_typing(context, chat_id))
    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, route_answer, query)
        answer = result["answer"]
        log.info("chat=%s конвеєр=%s", chat_id, result.get("pipeline"))
        if result.get("outcome") == "truncated":
            log.warning("chat=%s відповідь обрізана по MAX_TOKENS", chat_id)
            answer += ("\n\n(Відповідь вийшла задовгою і обрізалась. Спробуйте "
                      "запитати вужче — наприклад, про один конкретний аспект.)")
        elif result.get("outcome") not in (None, "ok"):
            log.warning("chat=%s outcome=%s пошуки=%s", chat_id, result.get("outcome"),
                       result.get("kb_searches"))
    except Exception:
        log.exception("Помилка обробки питання (chat=%s)", chat_id)
        answer = ("Сталася технічна помилка під час обробки питання. "
                 "Спробуйте, будь ласка, ще раз трохи пізніше.")
    finally:
        typing_task.cancel()

    for chunk in _split_for_telegram(answer):
        await update.message.reply_text(chunk)


async def usage_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Витрати з моменту запуску процесу — токени й $ по кожній моделі
    окремо (MODEL/MODEL_FAST мають різну ціну, core/cost.py). Лише
    ADMIN_CHAT_ID, якщо заданий — не бізнес-дані користувачів, але й не
    те, що варто світити будь-кому, хто напише боту команду."""
    chat_id = update.effective_chat.id
    if ADMIN_CHAT_ID and str(chat_id) != str(ADMIN_CHAT_ID):
        await update.message.reply_text("Ця команда доступна лише адміністратору бота.")
        return

    by_model = USAGE["by_model"]
    if not by_model:
        await update.message.reply_text(
            f"Ще жодного виклику моделі з моменту запуску процесу "
            f"({START_TIME:%d.%m.%Y %H:%M}).")
        return

    lines = [f"Витрати з моменту запуску процесу ({START_TIME:%d.%m.%Y %H:%M}):\n"]
    for row in cost.breakdown(by_model):
        lines.append(f"{row['model']}\n"
                     f"  викликів: {row['calls']}  вх: {row['in']}  вих: {row['out']}  "
                     f"${row['usd']:.4f}")
    lines.append(f"\nУсього: {USAGE['calls']} викликів, "
                 f"{USAGE['in']}+{USAGE['out']} токенів, ${cost.usd(by_model):.4f}")
    await update.message.reply_text("\n".join(lines))


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.exception("Необроблена помилка в обробнику", exc_info=context.error)


async def check_updates_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Раз на день: чи не вийшла нова редакція одного з відслідковуваних
    законів. Лише сповіщає — переіндексація (python ingest.py --reset)
    залишається ручним кроком, свідомо: законодавчі зміни варті перегляду
    людиною, перш ніж міняти базу знань агента."""
    log.info("Перевірка оновлень законодавства...")
    loop = asyncio.get_running_loop()
    try:
        updates = await loop.run_in_executor(None, check_for_updates)
    except Exception:
        log.exception("Не вдалося перевірити оновлення")
        return

    for u in updates:
        text = (f"Вийшла нова редакція: «{u['title']}»\n"
               f"{u['old']} → {u['new']}\n{u['url']}\n\n"
               f"Щоб оновити базу знань бота:  python ingest.py --reset")
        log.info("Знайдено оновлення: %s", text.replace("\n", " | "))
        await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=text)


def main() -> None:
    if not TELEGRAM_BOT_TOKEN:
        raise SystemExit(
            "Не знайдено TELEGRAM_BOT_TOKEN.\n"
            "  Отримайте токен у @BotFather (команда /newbot) і впишіть у .env"
        )

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(CommandHandler("usage", usage_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(on_error)

    if ADMIN_CHAT_ID:
        # час — локальний час сервера, де запущено процес
        app.job_queue.run_daily(check_updates_job, time=datetime.time(hour=9, minute=0))
        log.info("Щоденна перевірка оновлень увімкнена (09:00, сповіщення в chat_id=%s)",
                 ADMIN_CHAT_ID)
    else:
        log.warning("ADMIN_CHAT_ID не задано — щоденна перевірка оновлень вимкнена")

    log.info("Бот запущено (long polling). Ctrl+C — зупинити.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
