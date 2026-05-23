"""
Tool registry — the only file that knows which tool modules exist.

To add a new tool:
  1. Create bot/tools/my_tool.py with TOOL_DEF and execute().
  2. Import it here and add it to TOOL_MODULES.
  3. Done — ai_chat.py never needs to change.
"""

from bot.tools import (
    save_profile,
    get_buyer_profile,
    save_preferences,
    get_recommendations,
    search_listings,
    search_nearby_amenities,
)

TOOL_MODULES = [
    save_profile,
    get_buyer_profile,
    save_preferences,
    get_recommendations,
    search_listings,
    search_nearby_amenities,
]

# Built for ai_chat.py consumption
TOOLS = [m.TOOL_DEF for m in TOOL_MODULES]


async def execute_tool(name: str, inputs: dict, telegram_id: int) -> str:
    for module in TOOL_MODULES:
        if module.TOOL_DEF["name"] == name:
            return await module.execute(inputs, telegram_id)
    return f"Unknown tool: {name!r}"
