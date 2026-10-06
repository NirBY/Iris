"""Prometheus metrics (spec 13). `/metrics` is unauthenticated: do not expose it publicly."""

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Job

REGISTRY = CollectorRegistry()

WEBHOOKS = Counter(
    "iris_webhooks_total", "Webhook deliveries", ["instance", "result"], registry=REGISTRY
)
MESSAGES = Counter(
    "iris_messages_processed_total", "Classified messages", ["type", "verdict"], registry=REGISTRY
)
STAGE_SECONDS = Histogram(
    "iris_stage_duration_seconds", "Classification stage duration", ["stage"], registry=REGISTRY
)
PROVIDER_REQUESTS = Counter(
    "iris_provider_requests_total",
    "Outbound provider requests",
    ["provider", "endpoint", "status"],
    registry=REGISTRY,
)
PROVIDER_SECONDS = Histogram(
    "iris_provider_duration_seconds",
    "Outbound provider request duration",
    ["provider", "endpoint"],
    registry=REGISTRY,
)
TRANSCRIBED_AUDIO_SECONDS = Counter(
    "iris_transcription_seconds_audio_total",
    "Seconds of audio transcribed",
    ["provider"],
    registry=REGISTRY,
)
ALERTS = Counter(
    "iris_alerts_total",
    "Alerts by top category and delivery outcome",
    ["category", "delivery_status"],
    registry=REGISTRY,
)
JOBS = Gauge("iris_jobs", "Jobs by status", ["status"], registry=REGISTRY)

_JOB_STATUSES = ("queued", "running", "done", "failed", "dead")


def record_provider(provider: str, endpoint: str, status: str, seconds: float) -> None:
    PROVIDER_REQUESTS.labels(provider, endpoint, status).inc()
    PROVIDER_SECONDS.labels(provider, endpoint).observe(seconds)


async def render(db: AsyncSession) -> bytes:
    """Refresh the job gauge from the queue, then render all metrics."""
    counts = dict((await db.execute(select(Job.status, func.count()).group_by(Job.status))).all())
    for status in _JOB_STATUSES:
        JOBS.labels(status).set(int(counts.get(status, 0)))
    return generate_latest(REGISTRY)
