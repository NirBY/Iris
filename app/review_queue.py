"""Shared queue membership: AI work must not appear as an actionable human review."""

from sqlalchemy import ColumnElement, func, or_, select

from app.db.models import Job, Message, ReviewDataIssue


def unavailable_content() -> ColumnElement[bool]:
    """Route confirmed data failures separately; never create a human safety label.

    Exact machine reasons only. Inconclusive scores, unsupported documents/video,
    decoder failures and arbitrary provider errors still require review or recovery.
    Coalesce is necessary so a missing reason remains in the normal review queue.
    """
    reported = (
        select(ReviewDataIssue.message_id).where(ReviewDataIssue.message_id == Message.id).exists()
    )
    return or_(
        reported,
        func.coalesce(Message.review_reason, "").in_(
            (
                "OpenWA has no stored media for this message (check its inbound media storage)",
                "message has no media reference",
                "Unknown message type; no analyzable content",
            )
        ),
    )


def ai_pending() -> ColumnElement[bool]:
    active = (
        select(Job.id)
        .where(
            Job.type == "process_message",
            Job.status.in_(("queued", "running")),
            Job.payload["message_id"].as_integer() == Message.id,
        )
        .exists()
    )
    return or_(Message.status.in_(("pending", "processing")), active)
