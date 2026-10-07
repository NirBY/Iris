"""Publishes a live-update event after every committed change, from the tables it touched."""

from typing import Any

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.events import bus

# table (model class name) -> the parts of the portal that show it
TOPICS: dict[str, tuple[str, ...]] = {
    "Message": ("messages", "stats", "review"),
    "Classification": ("messages", "review"),
    "MessageReceipt": ("messages",),
    "MessageRevision": ("messages",),
    "StoredMedia": ("alerts", "messages"),
    "Alert": ("alerts", "stats"),
    "Job": ("jobs", "stats"),
    "Instance": ("instances", "stats"),
    "Chat": ("chats",),
    "ChatInstance": ("chats",),
}
_KEY = "iris_live"
_installed = False


def _after_flush(session: Session, _ctx: Any) -> None:
    state = session.info.setdefault(_KEY, {"topics": set(), "alerts": []})
    for obj in (*session.new, *session.dirty, *session.deleted):
        state["topics"].update(TOPICS.get(type(obj).__name__, ()))
    for obj in session.new:
        if type(obj).__name__ == "Alert":
            state["alerts"].append(obj.id)  # the primary key exists after the flush


def _after_commit(session: Session) -> None:
    state = session.info.pop(_KEY, None)
    if state is None:
        return
    for alert_id in state["alerts"] or [None]:
        bus.publish(*state["topics"], alert_id=alert_id)


def _after_rollback(session: Session) -> None:
    session.info.pop(_KEY, None)  # nothing was committed, so nothing changed


def install() -> None:
    """Hook every session (async sessions run on the sync Session class). Idempotent."""
    global _installed
    if _installed:
        return
    event.listen(Session, "after_flush", _after_flush)
    event.listen(Session, "after_commit", _after_commit)
    event.listen(Session, "after_rollback", _after_rollback)
    _installed = True
