# Розгортання на сервері

Той самий підхід, що й у `module1personalAgent` — постійний запуск через
**pm2**, автодеплой коду через GitHub Actions на пуш у `main`. Простіше:
`bot.py` — довгий polling без вхідного HTTP, тож Caddy/reverse-proxy/домен
тут не потрібні взагалі.

**Головна відмінність від module1personalAgent:** тут є ще й важка,
попередньо зібрана база (`laws.db` + `qdrant_data/`, ~430 МБ, 189
документів). Вона в `.gitignore` — `git pull` її ніколи не принесе.
Автодеплой коду і заливка БД — свідомо різні, не пов'язані кроки.

Файли для цього:
- `deploy/ecosystem.config.js` — pm2-конфіг (один процес, `lawyer-bot`)
- `deploy/deploy.sh` — `git pull` + залежності + `pm2 restart` (ручний і CI/CD той самий скрипт)
- `../deploy_data.sh` — окремо, лише для `laws.db`/`qdrant_data/` (не код)

## Передумови

- Той самий сервер і клон монорепо, що вже піднятий для
  `module1personalAgent` (`/home/ppv.codes/personaltrainer/AI_AGENTS`) —
  `module2Lawyer/` з'явиться в ньому після `git pull`, окремий clone не
  потрібен. **Якщо це інший сервер — постав нові GitHub-секрети
  (`DEPLOY_HOST`/`DEPLOY_USER`/`DEPLOY_SSH_KEY`) під іншим ім'ям і онови
  `deploy/deploy.sh` + `.github/workflows/deploy-lawyer-bot.yml`.**
- Вже встановлений **pm2** (той самий, що й для module1personalAgent —
  ставити вдруге не треба)

## 1. Код і залежності

```bash
cd /home/ppv.codes/personaltrainer/AI_AGENTS/module2Lawyer
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## 2. `.env`

```bash
cp .env.example .env
nano .env
```

Впиши `ANTHROPIC_API_KEY` і `TELEGRAM_BOT_TOKEN` (окремий бот від
module1personalAgent — інший токен від @BotFather). `ADMIN_CHAT_ID` —
необов'язково, потрібен лише для щоденних сповіщень про нову редакцію
закону (`watch.py`).

## 3. База знань — laws.db + qdrant_data

Це не код, автодеплой її не заливає. **З локальної машини** (де корпус
уже зібраний і перевірений — `python verify.py` чистий):

```bash
cd /Volumes/Nova/AI_AGENTS/module2Lawyer
DEPLOY_HOST=user@сервер DEPLOY_PATH=/home/ppv.codes/personaltrainer/AI_AGENTS/module2Lawyer \
  ./deploy_data.sh
```

Перший раз бот на сервері ще не запущений — на питання скрипта "bot.py
зупинено?" відповідай `y`. Далі, коли оновлюєш сам корпус (новий
`ingest.py --reset` локально), той самий скрипт — але вже реально
зупини `pm2 stop lawyer-bot` на сервері перед заливкою (embedded Qdrant
тримає файлову блокировку, живий процес заважає rsync).

## 4. pm2

```bash
cd /home/ppv.codes/personaltrainer/AI_AGENTS/module2Lawyer
pm2 start deploy/ecosystem.config.js
pm2 save
```

`pm2 startup` вже виконаний під час налаштування module1personalAgent —
вдруге не треба, той самий pm2-демон піднімає обидва проєкти разом із
сервером.

## Перевірка

```bash
pm2 status                 # має бути ще й lawyer-bot, поруч з personal-trainer-*
pm2 logs lawyer-bot        # логи наживо
```

Напиши боту в Telegram `/start` і питання на кшталт «яка дозволена
швидкість у населеному пункті» — має відповісти з цитатою пункту ПДР.

## Оновлення (ручний деплой коду)

```bash
/home/ppv.codes/personaltrainer/AI_AGENTS/module2Lawyer/deploy/deploy.sh
```

Якщо на сервері ще немає `laws.db`/`qdrant_data/`, скрипт зупиниться з
чіткою помилкою замість того, щоб мовчки перезапустити бота, який одразу
впаде — спершу крок 3.

## Оновлення бази знань

Окремо від коду і від автодеплою — лише коли реально змінився корпус
(нова партія законів, фікс парсера):

```bash
# локально
python ingest.py --reset
python verify.py          # переконатись, що чисто

# на сервері
pm2 stop lawyer-bot

# локально
DEPLOY_HOST=user@сервер DEPLOY_PATH=/home/ppv.codes/personaltrainer/AI_AGENTS/module2Lawyer \
  ./deploy_data.sh

# на сервері
pm2 start lawyer-bot
```

## CI/CD

Workflow `.github/workflows/deploy-lawyer-bot.yml` уже в репозиторії —
спрацьовує на пуш у `main`, якщо змінювалось щось у `module2Lawyer/`.
Використовує ті самі секрети, що й `deploy-personal-trainer-bot.yml`
(`DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY`) — якщо вони вже додані
для module1personalAgent і це той самий сервер, нічого додатково
налаштовувати не треба.

**Автодеплой коду ніколи не чіпає БД** — `laws.db`/`qdrant_data/` в
`.gitignore`, `deploy.sh` лише робить `git pull` + `pip install` + `pm2
restart`. Заливка бази (крок 3 вище) — завжди окрема, ручна дія.
