# Розгортання на сервері

Постійний запуск бота й дашборда на власному Linux-сервері (Ubuntu/Debian,
systemd): два systemd-сервіси з автоперезапуском + Caddy як reverse proxy з
автоматичним HTTPS замість тимчасового ngrok-тунелю.

Файли для цього лежать у `deploy/`:
- `personal-trainer-bot.service`, `personal-trainer-webapp.service` — systemd-юніти
- `Caddyfile` — reverse proxy з автоматичним Let's Encrypt
- `deploy.sh` — `git pull` + оновлення залежностей + рестарт сервісів (той самий скрипт і для ручного деплою, і для CI/CD)

## Передумови

- Сервер на Ubuntu/Debian з `sudo`-доступом
- Домен, A-запис якого вказує на IP цього сервера
- Відкриті порти 80 і 443 (для Caddy й видачі TLS-сертифіката)

## 1. Користувач для сервісів

Сервіси не мають працювати від root.

```bash
sudo useradd --system --create-home --shell /usr/sbin/nologin trainerbot
```

## 2. Код і залежності

```bash
sudo git clone https://github.com/FrankyJo/AI_AGENTS.git /opt/AI_AGENTS
cd /opt/AI_AGENTS/module1personalAgent
sudo python3 -m venv .venv
sudo .venv/bin/pip install -r requirements.txt
sudo chown -R trainerbot:trainerbot /opt/AI_AGENTS
```

## 3. `.env`

`.env` у git не потрапляє (є в `.gitignore`) — створюється вручну прямо на сервері.

```bash
sudo -u trainerbot cp .env.example .env
sudo -u trainerbot nano .env
```

Впиши:
- `ANTHROPIC_API_KEY`
- `TELEGRAM_BOT_TOKEN`
- `PUBLIC_BASE_URL=https://твій-домен.com` — реальний домен, більше не ngrok

## 4. Домен

У реєстратора домену додай A-запис: `твій-домен.com` → IP цього сервера.

## 5. Caddy (reverse proxy + автоматичний HTTPS)

`webapp/server.py` слухає лише `127.0.0.1:8000` — назовні дивиться тільки Caddy,
який сам випускає й оновлює TLS-сертифікат.

```bash
sudo apt install -y caddy   # або див. caddyserver.com/docs/install

sudo cp deploy/Caddyfile /etc/caddy/Caddyfile
sudo sed -i 's/yourdomain.com/твій-домен.com/' /etc/caddy/Caddyfile
sudo systemctl restart caddy
```

## 6. systemd-юніти

```bash
sudo cp deploy/personal-trainer-bot.service deploy/personal-trainer-webapp.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now personal-trainer-bot.service personal-trainer-webapp.service
```

## 7. Дозвіл на рестарт сервісів без пароля

Потрібно і для ручного деплою, і для майбутнього CI/CD — `deploy.sh` рестартує
сервіси через `sudo systemctl restart`.

```bash
echo 'trainerbot ALL=(root) NOPASSWD: /usr/bin/systemctl restart personal-trainer-bot.service, /usr/bin/systemctl restart personal-trainer-webapp.service' \
  | sudo tee /etc/sudoers.d/personal-trainer-bot
```

## Перевірка

```bash
sudo systemctl status personal-trainer-bot.service
sudo systemctl status personal-trainer-webapp.service
sudo journalctl -u personal-trainer-bot.service -f     # логи наживо
curl -I https://твій-домен.com/                         # має віддати 200
```

У Telegram: `/dashboard` має відкривати вже прод-домен, а не ngrok-адресу.
Локальний ngrok і `python -m bot.telegram_bot` на своїй машині можна гасити.

## Оновлення (ручний деплой)

```bash
sudo -u trainerbot /opt/AI_AGENTS/module1personalAgent/deploy/deploy.sh
```

## CI/CD (коли буде потрібно)

Workflow `.github/workflows/deploy-personal-trainer-bot.yml` уже в репозиторії
і спрацьовує при пуші в `main`, якщо змінювалось щось у `module1personalAgent/` —
але поки що мовчить, доки не додані секрети.

1. На сервері під `trainerbot` згенеруй ключ:
   ```bash
   sudo -u trainerbot ssh-keygen -t ed25519 -f /home/trainerbot/.ssh/id_ed25519 -N ""
   sudo -u trainerbot sh -c 'cat /home/trainerbot/.ssh/id_ed25519.pub >> /home/trainerbot/.ssh/authorized_keys'
   ```
2. У GitHub → Settings → Secrets and variables → Actions додай:
   - `DEPLOY_HOST` — IP або домен сервера
   - `DEPLOY_USER` — `trainerbot`
   - `DEPLOY_SSH_KEY` — вміст приватного ключа (`/home/trainerbot/.ssh/id_ed25519`)
3. Готово — наступний пуш у `main` сам зайде по SSH і прожене `deploy.sh`.
