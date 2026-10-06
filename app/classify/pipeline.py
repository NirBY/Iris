"""Run stages in order; stop at the first conclusive band (spec 8.4)."""

from dataclasses import dataclass, field
from typing import Literal

from app.classify.stages import ContextStage, ModerationStage, Stage, StageContext, StageResult
from app.db.models import Message

Verdict = Literal["safe", "harmful", "review"]


@dataclass
class PipelineOutcome:
    verdict: Verdict
    results: list[StageResult] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)  # categories that made it harmful
    max_score: float = 0.0


DEFAULT_STAGES: tuple[Stage, ...] = (ModerationStage(), ContextStage())


async def run_pipeline(
    message: Message, ctx: StageContext, stages: tuple[Stage, ...] = DEFAULT_STAGES
) -> PipelineOutcome:
    out = PipelineOutcome(verdict="review")
    for stage in stages:
        result = await stage.run(message, ctx)
        if result is None:
            continue
        out.results.append(result)
        if result.band == "safe":
            out.verdict = "safe"
            return out
        if result.band == "harmful":
            out.verdict = "harmful"
            out.categories = result.high_categories
            scores = result.scores
            out.max_score = max((float(scores[c]) for c in result.high_categories), default=0.0)
            return out
    # Every stage was inconclusive (or none applied beyond an inconclusive first one).
    if not out.results:
        raise ValueError("no stage applied to this message")
    return out
