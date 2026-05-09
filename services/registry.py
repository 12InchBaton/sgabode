"""
Service event registry — the ONLY place that wires services to events.

To add a new side effect to any event:
  1. Write your listener function in the relevant service module.
  2. Import it here and call bus.subscribe().

Nothing else needs to change.

Current event → listener map:
  listing.created        → matching.on_listing_created
  listing.created        → claude_service.on_listing_created_ai
  listing.media_uploaded → claude_service.on_floor_plan_uploaded
  match.created          → notification.on_match_created
"""

import logging

from events import bus

logger = logging.getLogger(__name__)


def register_all() -> None:
    """Subscribe all service listeners. Called once at application startup."""

    # ── Matching ──────────────────────────────────────────────────────────────
    from services.matching import on_listing_created as matching_on_listing_created

    bus.subscribe("listing.created", matching_on_listing_created)

    # ── AI enrichment ─────────────────────────────────────────────────────────
    from services.claude_service import (
        on_listing_created_ai,
        on_floor_plan_uploaded,
    )

    bus.subscribe("listing.created", on_listing_created_ai)
    bus.subscribe("listing.media_uploaded", on_floor_plan_uploaded)

    # ── Telegram notifications ─────────────────────────────────────────────────
    from services.notification import on_match_created

    bus.subscribe("match.created", on_match_created)

    logger.info("Service event listeners registered.")
