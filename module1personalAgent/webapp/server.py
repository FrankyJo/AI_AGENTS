"""
Веб-сервер Telegram Mini App: дашборд прогресу (профіль, програма, тоннаж по
тренуваннях, прогресія ваги по вправах). Окремий процес від бота:

    uvicorn webapp.server:app --host 0.0.0.0 --port 8000

Для тесту в самому Telegram потрібна публічна HTTPS-адреса (напр. ngrok-тунель
на цей порт) — вона йде в PUBLIC_BASE_URL у .env, за нею бот будує кнопку
WebApp у команді /dashboard.

Кожен запит /api/dashboard підписаний Telegram-ом (initData) — webapp/telegram_auth.py
перевіряє підпис і дістає з нього чий це chat_id, свій підмінити не можна.
"""

import pathlib

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from config import BOT_NAME, TELEGRAM_BOT_TOKEN
from domain import progress
from storage import store
from webapp.telegram_auth import InvalidInitData, validate_init_data

STATIC_DIR = pathlib.Path(__file__).parent / "static"

app = FastAPI(title="personal-trainer-dashboard")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/dashboard")
def dashboard(initData: str = Query(...)):
    try:
        user = validate_init_data(initData, TELEGRAM_BOT_TOKEN)
    except InvalidInitData as e:
        raise HTTPException(status_code=401, detail=str(e))

    chat_id = str(user["id"])
    data = store.load(chat_id)
    history = data["history"]

    exercise_names = sorted({ex["name"] for entry in history for ex in entry.get("exercises", [])})
    return {
        "bot_name": BOT_NAME,
        "profile": data["profile"],
        "program": data["program"],
        "total_workouts": len(history),
        "volume_series": progress.volume_series(history),
        "exercise_progression": {name: progress.exercise_progression(history, name)
                                  for name in exercise_names},
    }
