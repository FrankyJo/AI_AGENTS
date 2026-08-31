#!/usr/bin/env bash
# Ручний і CI/CD деплой в одному скрипті: підтягнути код, оновити
# залежності, перезапустити pm2-процес. Безпечно запускати повторно.
# Без sudo — pm2 керує процесом від імені того самого користувача,
# що його запустив.
#
#   ssh user@сервер '/шлях/до/AI_AGENTS/module2Lawyer/deploy/deploy.sh'
#
# НЕ чіпає laws.db/qdrant_data — вони в .gitignore, git pull їх не бачить.
# Перший запуск на новому сервері: спершу залити БД через
# ../deploy_data.sh (одноразово чи коли оновлюєш корпус), і лише
# ПОТІМ pm2 start deploy/ecosystem.config.js. Далі deploy.sh безпечний
# для будь-якого автодеплою коду — БД він не чіпає і не вимагає.
set -euo pipefail

# Той самий клон монорепо, що вже піднятий для module1personalAgent
# (module1personalAgent/deploy/deploy.sh) — module2Lawyer з'являється в
# ньому ж після git pull, окремий clone не потрібен.
REPO_DIR="/home/ppv.codes/personaltrainer/AI_AGENTS"
APP_DIR="$REPO_DIR/module2Lawyer"

cd "$REPO_DIR"
git pull --ff-only origin main

cd "$APP_DIR"
"$APP_DIR/.venv/bin/pip" install -q -r requirements.txt

if [[ ! -f laws.db || ! -d qdrant_data ]]; then
    echo "УВАГА: laws.db або qdrant_data/ відсутні на сервері — бот не" >&2
    echo "запуститься. Це не змінюється деплоєм коду: залий БД окремо" >&2
    echo "з локальної машини через ../deploy_data.sh (дивись DEPLOY.md)." >&2
    exit 1
fi

pm2 restart lawyer-bot

echo "Deployed $(git -C "$REPO_DIR" rev-parse --short HEAD)"
