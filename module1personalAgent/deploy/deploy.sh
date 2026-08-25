#!/usr/bin/env bash
# Ручний і CI/CD деплой в одному скрипті: підтягнути код, оновити залежності,
# перезапустити сервіси. Безпечно запускати повторно.
#
#   ssh trainerbot@сервер '/opt/AI_AGENTS/module1personalAgent/deploy/deploy.sh'
set -euo pipefail

REPO_DIR="/opt/AI_AGENTS"
APP_DIR="$REPO_DIR/module1personalAgent"

cd "$REPO_DIR"
git pull --ff-only origin main

cd "$APP_DIR"
"$APP_DIR/.venv/bin/pip" install -q -r requirements.txt

sudo systemctl restart personal-trainer-bot.service
sudo systemctl restart personal-trainer-webapp.service

echo "Deployed $(git -C "$REPO_DIR" rev-parse --short HEAD)"
