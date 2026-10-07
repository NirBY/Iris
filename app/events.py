"""Live updates: an in-process bus the portal listens to over Server-Sent Events.

Events say only WHICH parts of the data changed (and the id of a new alert), never what the data
is: the page refetches through the normal, authenticated API, so every visibility and withholding
rule still applies and nothing sensitive can leak through the stream. Iris is a single process,
so a process-local bus is enough.
"""

import asyncio
import contextlib
from dataclasses import dataclass, field

from app.metrics import LIVE_CLIENTS

TOPICS = ("messages", "alerts", "review", "jobs", "stats", "instances", "chats")
MAX_CLIENTS = 20
COALESCE_SECONDS = 0.3  # changes this close together become one event
QUEUE_SIZE = 16


class TooManyClients(Exception):
    pass


@dataclass(eq=False)
class Subscription:
    queue: asyncio.Queue[dict[str, object] | None] = field(
        default_factory=lambda: asyncio.Queue(QUEUE_SIZE)
    )


class EventBus:
    def __init__(self) -> None:
        self._subs: set[Subscription] = set()
        self._topics: set[str] = set()
        self._alert_ids: list[int] = []
        self._timer: asyncio.TimerHandle | None = None

    @property
    def clients(self) -> int:
        return len(self._subs)

    def subscribe(self) -> Subscription:
        if len(self._subs) >= MAX_CLIENTS:
            raise TooManyClients
        sub = Subscription()
        self._subs.add(sub)
        LIVE_CLIENTS.set(len(self._subs))
        return sub

    def unsubscribe(self, sub: Subscription) -> None:
        self._subs.discard(sub)
        LIVE_CLIENTS.set(len(self._subs))

    def publish(self, *topics: str, alert_id: int | None = None) -> None:
        """Note a change; one event goes out shortly after. Safe to call from any async code."""
        if not self._subs:
            return
        self._topics.update(t for t in topics if t in TOPICS)
        if alert_id is not None:
            self._alert_ids.append(alert_id)
        if self._timer is None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                return  # no event loop (a migration thread): nobody is listening here
            self._timer = loop.call_later(COALESCE_SECONDS, self._flush)

    def _flush(self) -> None:
        self._timer = None
        topics, alerts = sorted(self._topics), self._alert_ids
        self._topics, self._alert_ids = set(), []
        events: list[dict[str, object]] = []
        if topics:
            events.append({"event": "change", "topics": topics})
        events += [{"event": "alert", "id": i} for i in alerts]
        for sub in list(self._subs):
            try:
                for event in events:
                    sub.queue.put_nowait(event)
            except asyncio.QueueFull:
                # A client that cannot keep up is dropped; its browser reconnects and catches up.
                self._drop(sub)

    def _drop(self, sub: Subscription) -> None:
        self.unsubscribe(sub)
        with contextlib.suppress(asyncio.QueueFull):
            while not sub.queue.empty():
                sub.queue.get_nowait()
            sub.queue.put_nowait(None)

    async def close_all(self) -> None:
        """Shutdown: end every open stream."""
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        for sub in list(self._subs):
            self._drop(sub)


bus = EventBus()
