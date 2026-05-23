"""
Onboarding handler — /start command.

Clears the user's AI conversation history and sends a welcome message.
All subsequent messages are handled by ai_chat.py (the AI catch-all handler).
"""

import logging

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

logger = logging.getLogger(__name__)

_WELCOME = (
    "👋 Welcome to *SGAbode* — Singapore's smartest property discovery bot!\n\n"
    "I'm your AI property advisor. Just tell me what you're looking for in plain English:\n"
    "buying or renting, your budget, preferred areas, property type — and I'll handle the rest.\n\n"
    "To get started, what's your name?"
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reset conversation history and greet the user."""
    context.user_data.clear()
    # Seed history as a user→assistant pair. The Anthropic API requires the first
    # message to be from the user, so we use a synthetic opener.
    context.user_data["ai_history"] = [
        {"role": "user", "content": "Hello, I want to find a property in Singapore."},
        {"role": "assistant", "content": [{"type": "text", "text": _WELCOME}]},
    ]
    await update.message.reply_text(_WELCOME, parse_mode="Markdown")


def register(app: Application) -> None:
    """Called by bot/handlers/registry.py."""
    app.add_handler(CommandHandler("start", start))
