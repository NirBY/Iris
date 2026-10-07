"""/api/events: Server-Sent Events that tell the open portal what changed (never the content)."""

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.events import TooManyClients, bus
from app.security.auth import current_user

router = APIRouter(prefix="/api/events", tags=["events"], dependencies=[Depends(current_user)])
HEARTBEAT_SECONDS = 20  # keeps proxies and tunnels from closing an idle stream


def _frame(event: dict[str, object]) -> str:
    body = {k: v for k, v in event.items() if k != "event"}
    return f"event: {event['event']}\ndata: {json.dumps(body)}\n\n"


@router.get("")
async def stream() -> StreamingResponse:
    try:
        sub = bus.subscribe()
    except TooManyClients:
        raise HTTPException(429, "Too many open portals. Close one and try again.") from None

    async def frames() -> AsyncIterator[str]:
        try:
            yield "retry: 3000\n\n"
            yield _frame({"event": "hello"})
            while True:
                try:
                    item = await asyncio.wait_for(sub.queue.get(), HEARTBEAT_SECONDS)
                except TimeoutError:
                    yield ": ping\n\n"
                    continue
                if item is None:
                    return
                yield _frame(item)
        finally:
            bus.unsubscribe(sub)

    return StreamingResponse(
        frames(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",  # nginx: do not hold the stream back
        },
    )
