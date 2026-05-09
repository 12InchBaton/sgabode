"""
Lightweight async event bus.

Usage
-----
Emitting (any module):
    from events import bus
    await bus.emit("listing.created", listing_id=42)

Subscribing (in services/registry.py):
    from events import bus
    from services.matching import on_listing_created

    bus.subscribe("listing.created", on_listing_created)

Defined event names and their payload kwargs:
    listing.created          listing_id: int
    listing.media_uploaded   listing_id: int, media_id: int, media_type: str
    match.created            match_id: int, buyer_id: int, listing_id: int, telegram_id: int
    viewing.requested        viewing_request_id: int
"""

import asyncio
import logging
from collections import defaultdict
from typing import Callable

logger = logging.getLogger(__name__)


class EventBus:
    def __init__(self) -> None:
        self._listeners: dict[str, list[Callable]] = defaultdict(list)

    def subscribe(self, event: str, fn: Callable) -> None:
        """Register *fn* as a listener for *event*."""
        if fn not in self._listeners[event]:
            self._listeners[event].append(fn)
            logger.debug("Subscribed %s to event '%s'", fn.__qualname__, event)

    def unsubscribe(self, event: str, fn: Callable) -> None:
        try:
            self._listeners[event].remove(fn)
        except ValueError:
            pass

    async def emit(self, event: str, **payload) -> None:
        """
        Call every listener registered for *event*.
        Each listener receives payload as keyword arguments.
        Errors are logged and isolated — one failing listener does not block others.
        """
        listeners = self._listeners.get(event, [])
        if not listeners:
            return
        for fn in listeners:
            try:
                if asyncio.iscoroutinefunction(fn):
                    await fn(**payload)
                else:
                    fn(**payload)
            except Exception:
                logger.exception(
                    "Unhandled error in listener '%s' for event '%s'",
                    fn.__qualname__,
                    event,
                )


# Module-level singleton — import this everywhere
bus = EventBus()
