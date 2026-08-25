// pm2-конфіг для бота й дашборда. Шляхи рахуються відносно цього файлу
// (module1personalAgent/deploy/ecosystem.config.js), тому працює незалежно
// від того, куди саме склонований репозиторій.
//
//   pm2 start deploy/ecosystem.config.js
//   pm2 save
//   pm2 startup   // разово, щоб pm2 піднімався разом із сервером

const path = require("path");
const APP_DIR = path.resolve(__dirname, "..");

module.exports = {
  apps: [
    {
      name: "personal-trainer-bot",
      cwd: APP_DIR,
      script: `${APP_DIR}/.venv/bin/python`,
      args: "-m bot.telegram_bot",
      interpreter: "none",
      autorestart: true,
      max_restarts: 20,
    },
    {
      name: "personal-trainer-webapp",
      cwd: APP_DIR,
      script: `${APP_DIR}/.venv/bin/uvicorn`,
      args: "webapp.server:app --host 127.0.0.1 --port 8000",
      interpreter: "none",
      autorestart: true,
      max_restarts: 20,
    },
  ],
};
