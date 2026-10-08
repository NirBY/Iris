"""Opt-in OpenWA session readiness checks; no message bodies or credentials retained."""

from datetime import UTC, datetime
from urllib.parse import quote

from prometheus_client import Gauge
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Instance
from app.metrics import REGISTRY
from app.openwa.client import OpenWAClient, OpenWAError
from app.security.crypto import decrypt

SESSION_READY = Gauge(
    "iris_session_ready",
    "Last session probe: 1 ready, 0 unavailable",
    ["instance"],
    registry=REGISTRY,
)
states: dict[int, bool] = {}
session_details: dict[int, tuple[str, datetime]] = {}


async def probe_instance(instance: Instance, key: bytes) -> None:
    status = "unreachable"
    if instance.openwa_api_key_enc:
        client = OpenWAClient(instance.openwa_base_url, decrypt(key, instance.openwa_api_key_enc))
        try:
            data = await client._request(
                "GET", "/api/sessions/" + quote(instance.openwa_instance_id, safe="")
            )
            body = data.get("data", data) if isinstance(data, dict) else {}
            allowed = {
                "ready",
                "created",
                "initializing",
                "authenticating",
                "qr_ready",
                "disconnected",
                "failed",
                "action_required",
            }
            candidate = str(body.get("status", "")).lower() if isinstance(body, dict) else ""
            status = candidate if candidate in allowed else "unknown"
        except OpenWAError as exc:
            status = "missing" if exc.status == 404 else "unreachable"
        finally:
            await client.aclose()
    states[instance.id] = status == "ready"
    session_details[instance.id] = (status, datetime.now(UTC))
    SESSION_READY.labels(str(instance.id)).set(int(status == "ready"))


async def probe_sessions(factory: async_sessionmaker[AsyncSession], key: bytes) -> None:
    async with factory() as db:
        instances = list((await db.scalars(select(Instance))).all())
    active = {instance.id for instance in instances}
    for obsolete in set(states) - active:
        states.pop(obsolete)
        session_details.pop(obsolete, None)
        SESSION_READY.remove(str(obsolete))
    for instance in instances:
        await probe_instance(instance, key)
