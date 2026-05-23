"""
Onboarding handler — /start command.

Clears the user's AI conversation history and sends a welcome message.
All subsequent messages are handled by ai_chat.py (the AI catch-all handler).
"""

import logging

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from services.session_service import clear_history

logger = logging.getLogger(__name__)

_WELCOME = (
    "👋 Welcome to *SGAbode* — Singapore's smartest property discovery bot!\n\n"
    "I'm your AI property advisor. Just tell me what you're looking for in plain English:\n"
    "buying or renting, your budget, preferred areas, property type — and I'll handle the rest.\n\n"
    "To get started, what's your name?"
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reset conversation history and greet the user."""
    telegram_id = update.effective_user.id
    context.user_data.clear()

    # Clear persisted history in DB so fresh conversation starts clean
    await clear_history(telegram_id)

    # Seed in-memory history as a user→assistant pair.
    # The Anthropic API requires the first message to be from the user.
    seed = [
        {"role": "user", "content": "Hello, I want to find a property in Singapore."},
        {"role": "assistant", "content": [{"type": "text", "text": _WELCOME}]},
    ]
    context.user_data["ai_history"] = seed
    await update.message.reply_text(_WELCOME, parse_mode="Markdown")


def register(app: Application) -> None:
    """Called by bot/handlers/registry.py."""
    app.add_handler(CommandHandler("start", start))
