#!/usr/bin/env bash
# Одноразова (або "коли оновив корпус") заливка laws.db + qdrant_data/ на
# прод — БЕЗ git. Ці два шляхи в .gitignore навмисно: код деплоїться як
# завгодно (git pull, CI тощо), а дані — окремим кроком, лише коли самі
# дані змінилися (новий python ingest.py --reset локально), а не на
# кожен деплой коду.
#
# Налаштування — змінні оточення (нічого не хардкодиться і не летить у git):
#   DEPLOY_HOST=user@myserver.example.com
#   DEPLOY_PATH=/opt/module2lawyer          # шлях до проєкту НА сервері
#
# Використання:
#   DEPLOY_HOST=deploy@1.2.3.4 DEPLOY_PATH=/opt/module2lawyer ./deploy_data.sh
#   ./deploy_data.sh --dry-run             # показати, що поїде, нічого не чіпаючи

set -euo pipefail
cd "$(dirname "$0")"

if [[ -z "${DEPLOY_HOST:-}" || -z "${DEPLOY_PATH:-}" ]]; then
    echo "Потрібні DEPLOY_HOST і DEPLOY_PATH. Приклад:" >&2
    echo "  DEPLOY_HOST=deploy@1.2.3.4 DEPLOY_PATH=/opt/module2lawyer $0" >&2
    exit 1
fi

DRY_RUN=""
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN="--dry-run"

if [[ ! -f laws.db || ! -d qdrant_data ]]; then
    echo "laws.db або qdrant_data/ не знайдено тут — спершу:  python ingest.py" >&2
    exit 1
fi

echo "→ ${DEPLOY_HOST}:${DEPLOY_PATH}/  (laws.db: $(du -h laws.db | cut -f1), qdrant_data: $(du -sh qdrant_data | cut -f1))"
echo
echo "УВАГА: bot.py тримає Qdrant (local mode, файлове сховище з"
echo "блокуванням) відкритим у пам'яті весь час роботи процесу — rsync"
echo "у директорію, яку тримає відкритою живий процес, ризикує побити"
echo "індекс. Перш ніж продовжити, зупини bot.py НА СЕРВЕРІ (${DEPLOY_HOST})."
if [[ -z "$DRY_RUN" ]]; then
    read -r -p "bot.py на сервері зупинено? [y/N] " confirm
    [[ "$confirm" == "y" || "$confirm" == "Y" ]] || { echo "Скасовано."; exit 1; }
fi

# --checksum, не --times: файли можуть перегенеровуватись з іншою mtime,
# але з тим самим вмістом — без цього rsync ганяв би 400+ МБ щоразу
# даремно. -e ssh нічого не додає понад дефолт, лишено явним для ясності.
rsync -avz --checksum --progress $DRY_RUN -e ssh \
    laws.db "${DEPLOY_HOST}:${DEPLOY_PATH}/laws.db"
rsync -avz --checksum --progress $DRY_RUN -e ssh \
    qdrant_data/ "${DEPLOY_HOST}:${DEPLOY_PATH}/qdrant_data/"

echo "✓ Скопійовано. Тепер запусти bot.py на сервері знову — він відкриє"
echo "  Qdrant/SQLite заново і побачить нові дані."
