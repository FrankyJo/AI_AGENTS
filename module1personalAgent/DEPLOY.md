# Розгортання на сервері

Постійний запуск бота й дашборда через **pm2** (замість systemd — простіше,
не вимагає окремого системного користувача) + Caddy як reverse proxy з
автоматичним HTTPS замість тимчасового ngrok-тунелю.

Файли для цього лежать у `deploy/`:
- `ecosystem.config.js` — pm2-конфіг для двох процесів (бот + дашборд)
- `Caddyfile` — reverse proxy з автоматичним Let's Encrypt
- `deploy.sh` — `git pull` + оновлення залежностей + `pm2 restart` (той самий скрипт і для ручного деплою, і для CI/CD)

## Передумови

- Сервер на Ubuntu/Debian, `sudo`-доступ, вже встановлений **pm2** (`npm i -g pm2`)
- Домен, A-запис якого вказує на IP цього сервера
- Відкриті порти 80 і 443 (для Caddy й видачі TLS-сертифіката)

Окремий системний користувач не потрібен — все працює від твого звичайного
користувача (того, під яким запускаєш pm2).

## 1. Код і залежності

```bash
cd /home/ppv.codes/personaltrainer
git clone https://github.com/FrankyJo/AI_AGENTS.git
cd AI_AGENTS/module1personalAgent
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Якщо клонування зробили через sudo і каталог вийшов root-own:

```bash
sudo chown -R $(whoami):$(whoami) /home/ppv.codes/personaltrainer/AI_AGENTS
```

## 2. `.env`

`.env` у git не потрапляє (є в `.gitignore`) — створюється вручну прямо на сервері.

```bash
cp .env.example .env
nano .env
```

Впиши:
- `ANTHROPIC_API_KEY`
- `TELEGRAM_BOT_TOKEN`
- `PUBLIC_BASE_URL=https://твій-домен.com` — реальний домен, більше не ngrok

## 3. Домен

У реєстратора домену додай A-запис: `твій-домен.com` → IP цього сервера.

## 4. Reverse proxy + HTTPS

`webapp/server.py` слухає лише `127.0.0.1:8000` — назовні до нього має
дивитись єдиний веб-сервер на портах 80/443. Який саме — залежить від сервера:

### Варіант A — чистий VPS, порти 80/443 вільні

Caddy сам випускає й оновлює TLS-сертифікат, конфіг у `deploy/Caddyfile`.

Caddy немає в стандартних репозиторіях Debian/Ubuntu — треба додати офіційний
apt-репозиторій ([caddyserver.com/docs/install](https://caddyserver.com/docs/install#debian-ubuntu-raspbian)):

```bash
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
  | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
  | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update
sudo apt install -y caddy

sudo cp deploy/Caddyfile /etc/caddy/Caddyfile
sudo sed -i 's/yourdomain.com/твій-домен.com/' /etc/caddy/Caddyfile
sudo systemctl restart caddy
```

Якщо `sudo ss -tlnp | grep -E ':80 |:443 '` показує, що порти вже зайняті
(litespeed, nginx, apache тощо) — це не твій випадок, дивись варіант B.

### Варіант B — сервер уже під панеллю (CyberPanel/LiteSpeed) — цей випадок

Порти 80/443 тримає LiteSpeed заради інших сайтів на цьому VPS — Caddy тут не
ставимо (`sudo systemctl disable --now caddy`, якщо встиг запустити). Прокидуємо
через саму панель:

1. **CyberPanel → Websites → Create Website** (або Create Child Domain, якщо
   `personaltrainer.ppv.codes` — піддомен уже доданого `ppv.codes`) — переконайся,
   що сайт для цього домену існує.
2. **Websites → List Websites → [домен] → Manage → SSL → Issue SSL** —
   випустить Let's Encrypt сертифікат (тепер спрацює, бо порт 80 вільний від
   зациклених спроб Caddy).
3. **Manage → Rewrite Rules** для цього сайту, додати:
   ```
   RewriteEngine On
   RewriteRule ^(.*)$ http://127.0.0.1:8000$1 [P,L]
   ```
   Якщо `[P]`-проксі через rewrite поводиться нестабільно — надійніший спосіб:
   **Manage → vHost Conf** (сирий конфіг OpenLiteSpeed) і додати нативний proxy:
   ```
   extprocessor personaltrainer-app {
     type                    proxy
     address                 127.0.0.1:8000
     maxConns                100
     pcKeepAliveTimeout      60
     connTimeout             5
     retryTimeout            0
   }
   context / {
     type                    proxy
     handler                 personaltrainer-app
     addDefaultCharset       off
   }
   ```
4. Перезапусти LiteSpeed (кнопка в CyberPanel, або `sudo systemctl restart lsws`).

## 5. pm2

```bash
cd /home/ppv.codes/personaltrainer/AI_AGENTS/module1personalAgent
pm2 start deploy/ecosystem.config.js
pm2 save          # запам'ятати поточний список процесів
pm2 startup       # виведе одну sudo-команду — виконай її, щоб pm2 піднімався разом із сервером
```

## Перевірка

```bash
pm2 status
pm2 logs personal-trainer-bot          # логи наживо
curl -I https://твій-домен.com/         # має віддати 200
```

У Telegram: `/dashboard` має відкривати вже прод-домен, а не ngrok-адресу.
Локальний ngrok і `python -m bot.telegram_bot` на своїй машині можна гасити.

## Оновлення (ручний деплой)

```bash
/home/ppv.codes/personaltrainer/AI_AGENTS/module1personalAgent/deploy/deploy.sh
```

### Разова міграція на SQLite

Storage перейшов з окремих `storage/data/<chat_id>.json` на єдиний
`storage/data/app.db` (SQLite). Якщо на сервері вже є старі JSON-файли з
реальними даними користувачів — після цього деплою вони "зникнуть" (store.py
дивиться вже в БД), поки не прогониш міграцію ОДИН раз:

```bash
cd /home/ppv.codes/personaltrainer/AI_AGENTS/module1personalAgent
.venv/bin/python scripts/migrate_json_to_sqlite.py
pm2 restart personal-trainer-bot personal-trainer-webapp
```

Старі `.json`-файли скрипт не видаляє — перевір, що дані на місці, і приберіть
вручну, коли переконаєшся.

## CI/CD (коли буде потрібно)

Workflow `.github/workflows/deploy-personal-trainer-bot.yml` уже в репозиторії
і спрацьовує при пуші в `main`, якщо змінювалось щось у `module1personalAgent/` —
але поки що мовчить, доки не додані секрети.

1. На сервері (під своїм користувачем) згенеруй ключ для деплою:
   ```bash
   ssh-keygen -t ed25519 -f ~/.ssh/deploy_key -N ""
   cat ~/.ssh/deploy_key.pub >> ~/.ssh/authorized_keys
   ```
2. У GitHub → Settings → Secrets and variables → Actions додай:
   - `DEPLOY_HOST` — IP або домен сервера
   - `DEPLOY_USER` — твій користувач на сервері
   - `DEPLOY_SSH_KEY` — вміст приватного ключа (`~/.ssh/deploy_key`)
3. Готово — наступний пуш у `main` сам зайде по SSH і прожене `deploy.sh`
   (`pm2 restart` не потребує sudo, бо працює від того самого користувача).
