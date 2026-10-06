"""Job handlers. `process_message` classifies one stored message."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import timedelta

from loguru import logger
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.classify.pipeline import PipelineOutcome, run_pipeline
from app.classify.stages import StageContext
from app.classify.thresholds import effective_thresholds
from app.db.models import Classification, Message
from app.jobs.queue import ClaimedJob, PermanentError
from app.providers import Providers
from app.settings_store import get_secret, get_setting

HarmfulHook = Callable[[AsyncSession, Message, PipelineOutcome], Awaitable[None]]


async def _no_alerts_yet(_db: AsyncSession, message: Message, outcome: PipelineOutcome) -> None:
    logger.info(
        "message {} is harmful ({}); alert service not wired", message.id, outcome.categories
    )


@dataclass
class Deps:
    session_factory: async_sessionmaker[AsyncSession]
    providers: Providers
    key_bytes: bytes
    on_harmful: HarmfulHook = field(default=_no_alerts_yet)


async def process_message(job: ClaimedJob, deps: Deps) -> None:
    message_id = job.payload.get("message_id")
    if not isinstance(message_id, int):
        raise PermanentError("job payload has no message_id")
    async with deps.session_factory() as db:
        message = await db.get(Message, message_id)
        if message is None:
            raise PermanentError("message no longer exists")
        if message.redacted:
            message.status = "skipped"  # redacted content is never reprocessed
            await db.commit()
            return
        if message.type != "text":
            # Media (images, audio, video) is handled by the media pipeline (milestone 4).
            message.status = "skipped"
            await db.commit()
            return

        message.status = "processing"
        await db.execute(delete(Classification).where(Classification.message_id == message.id))
        await db.commit()

        api_key = await get_secret(db, "openai.api_key", deps.key_bytes)
        if not api_key:
            raise PermanentError("OpenAI API key is not configured")
        ctx = StageContext(
            db=db,
            moderator=deps.providers.moderation(api_key),
            model=str(await get_setting(db, "classification.model")),
            thresholds=effective_thresholds(await get_setting(db, "classification.thresholds")),
            context_window_size=int(await get_setting(db, "classification.context_window_size")),
            context_max_age=timedelta(
                hours=int(await get_setting(db, "classification.context_max_age_hours"))
            ),
        )
        try:
            outcome = await run_pipeline(message, ctx)
        except ValueError:
            message.status = "skipped"  # nothing to classify (empty text)
            await db.commit()
            return

        for r in outcome.results:
            db.add(
                Classification(
                    message_id=message.id,
                    stage=r.stage,
                    input_kind=r.input_kind,
                    model=r.model,
                    scores=r.scores,
                    flagged_categories=r.flagged_categories,
                    band=r.band,
                    context_message_ids=r.context_message_ids,
                    latency_ms=r.latency_ms,
                )
            )
        message.verdict = outcome.verdict
        message.status = "done"
        await db.commit()
        logger.info(
            "message {} classified: verdict={} stages={}",
            message.id,
            outcome.verdict,
            [r.stage for r in outcome.results],
        )
        if outcome.verdict == "harmful":
            await deps.on_harmful(db, message, outcome)
