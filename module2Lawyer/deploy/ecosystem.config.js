// pm2-конфіг для бота. Шляхи рахуються відносно цього файлу
// (module2Lawyer/deploy/ecosystem.config.js), тому працює незалежно
// від того, куди саме склонований репозиторій.
//
//   pm2 start deploy/ecosystem.config.js
//   pm2 save
//   pm2 startup   // разово, щоб pm2 піднімався разом із сервером
//
// На відміну від module1personalAgent — жодного веб-процесу й
// reverse-proxy не треба: bot.py довгий polling, без вхідного HTTP.

const path = require("path");
const APP_DIR = path.resolve(__dirname, "..");

module.exports = {
  apps: [
    {
      name: "lawyer-bot",
      cwd: APP_DIR,
      script: `${APP_DIR}/.venv/bin/python`,
      args: "bot.py",
      interpreter: "none",
      autorestart: true,
      max_restarts: 20,
    },
  ],
};
