"""
Route registry — the only file that knows which routers exist.

To add a new feature domain:
  1. Create routes/agents.py (or whatever) with a `router` object.
  2. Import it here and add it to ROUTERS.
  3. Done — main.py never needs to change.
"""

from routes import buyers, listings, payments, scraper, viewing

ROUTERS = [
    buyers.router,
    listings.router,
    viewing.router,
    payments.router,
    scraper.router,
]
