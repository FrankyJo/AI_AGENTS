#!/usr/bin/env bash
# Ручний і CI/CD деплой в одному скрипті: підтягнути код, оновити залежності,
# перезапустити pm2-процеси. Безпечно запускати повторно. Без sudo — pm2
# керує процесами від імені того самого користувача, що його запустив.
#
#   ssh user@сервер '/opt/AI_AGENTS/module1personalAgent/deploy/deploy.sh'
set -euo pipefail

REPO_DIR="/opt/AI_AGENTS"
APP_DIR="$REPO_DIR/module1personalAgent"

cd "$REPO_DIR"
git pull --ff-only origin main

cd "$APP_DIR"
"$APP_DIR/.venv/bin/pip" install -q -r requirements.txt

pm2 restart personal-trainer-bot personal-trainer-webapp

echo "Deployed $(git -C "$REPO_DIR" rev-parse --short HEAD)"
