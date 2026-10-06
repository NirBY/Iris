"""OpenAI Moderation client (free endpoint, rate limited)."""

import contextlib
import math
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.jobs.queue import PermanentError, TransientError

URL = "https://api.openai.com/v1/moderations"
_TIMEOUT = httpx.Timeout(30.0)


@dataclass
class ModerationResult:
    scores: dict[str, float]
    flagged: bool
    api_categories: dict[str, bool]
    applied_input_types: dict[str, list[str]] = field(default_factory=dict)
    model: str = ""

    def stored_scores(self) -> dict[str, Any]:
        """Flat category->score map plus `_meta` (API flag and which input types were scored)."""
        return {
            **self.scores,
            "_meta": {
                "api_flagged": self.flagged,
                "api_categories": self.api_categories,
                "applied_input_types": self.applied_input_types,
            },
        }


class ModerationClient:
    def __init__(self, api_key: str, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._client = httpx.AsyncClient(
            headers={"Authorization": f"Bearer {api_key}"}, timeout=_TIMEOUT, transport=transport
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def moderate(self, model: str, input_: str | list[dict[str, Any]]) -> ModerationResult:
        try:
            r = await self._client.post(URL, json={"model": model, "input": input_})
        except httpx.HTTPError as exc:
            raise TransientError(f"moderation unreachable: {exc.__class__.__name__}") from exc
        if r.status_code == 429 or r.status_code >= 500:
            retry_after: float | None = None
            with contextlib.suppress(ValueError):
                parsed = float(r.headers.get("retry-after", ""))
                if math.isfinite(parsed):
                    retry_after = min(max(parsed, 0.0), 3600.0)
            raise TransientError(f"moderation HTTP {r.status_code}", retry_after=retry_after)
        if r.status_code >= 400:
            # 400 bad input, 401/403 bad key: retrying cannot help until fixed.
            raise PermanentError(f"moderation HTTP {r.status_code}")
        try:
            res = r.json()["results"][0]
            return ModerationResult(
                scores={k: float(v) for k, v in res["category_scores"].items()},
                flagged=bool(res.get("flagged")),
                api_categories={k: bool(v) for k, v in res.get("categories", {}).items()},
                applied_input_types=res.get("category_applied_input_types") or {},
                model=str(r.json().get("model", model)),
            )
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise TransientError("moderation returned an unexpected response") from exc
