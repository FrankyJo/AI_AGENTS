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
git clone https://github.com/FrankyJo/AI_AGENTS.git /opt/AI_AGENTS
cd /opt/AI_AGENTS/module1personalAgent
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Якщо `/opt` вимагає sudo для клонування і репозиторій виявився root-own:

```bash
sudo chown -R $(whoami):$(whoami) /opt/AI_AGENTS
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

## 4. Caddy (reverse proxy + автоматичний HTTPS)

`webapp/server.py` слухає лише `127.0.0.1:8000` — назовні дивиться тільки Caddy,
який сам випускає й оновлює TLS-сертифікат.

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

## 5. pm2

```bash
cd /opt/AI_AGENTS/module1personalAgent
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
/opt/AI_AGENTS/module1personalAgent/deploy/deploy.sh
```

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
