module.exports = {
  apps: [
    {
      name: "tuyabot",
      script: "bot.py",
      interpreter: "./venv/bin/python",
      cwd: __dirname,
      autorestart: true,
      max_restarts: 10,
      min_uptime: "10s",
      log_file: "./bot.log",
      env: {
        PYTHONUNBUFFERED: "1"
      }
    }
  ]
};
