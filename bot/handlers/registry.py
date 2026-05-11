"""
Bot handler registry — the only file that knows which handler modules exist.

To add a new feature (e.g. agent commands, admin panel):
  1. Create bot/handlers/agents.py with a register(app) function.
  2. Import it here and add it to HANDLER_MODULES.
  3. Done — bot/bot.py never needs to change.

Handler order matters for python-telegram-bot: ConversationHandlers must come
before generic MessageHandlers that might overlap. Order in HANDLER_MODULES
controls registration order.
"""

from telegram.ext import Application

from bot.handlers import onboarding, preferences, listings, recommendations

# Ordered list — ConversationHandlers first
HANDLER_MODULES = [
    onboarding,       # /start ConversationHandler (highest priority)
    preferences,      # /update ConversationHandler + /preferences command
    listings,         # /liked, /help, /like_N, /skip_N, /view_N
    recommendations,  # /recommend — ranked listings with AI reasons
]


def register_all(app: Application) -> None:
    """Register every handler module. Called once in bot/bot.py."""
    for module in HANDLER_MODULES:
        module.register(app)
