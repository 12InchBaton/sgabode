"""
Telegram bot entry point.

To add new commands or conversations:
  → Create a handler module in bot/handlers/
  → Add it to bot/handlers/registry.py
  → Done. Nothing here changes.
"""

import logging

from telegram.ext import Application

from config import settings
from bot.handlers.registry import register_all

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def build_application() -> Application:
    app = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).build()
    register_all(app)
    return app


def run() -> None:
    app = build_application()
    logger.info("SGAbode bot starting (long polling)...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    run()
