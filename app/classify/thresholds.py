"""Per-category thresholds and banding (spec 8.3). Uses category_scores, never `flagged`."""

from typing import Any, Literal

Band = Literal["safe", "harmful", "inconclusive"]
Thresholds = dict[str, tuple[float, float]]  # category -> (low, high)

_SELF_HARM = (0.10, 0.40)
_THREAT = (0.15, 0.50)
_GRAPHIC = (0.15, 0.60)
_GENERAL = (0.20, 0.70)

DEFAULT_THRESHOLDS: Thresholds = {
    "sexual/minors": (0.05, 0.30),
    "self-harm": _SELF_HARM,
    "self-harm/intent": _SELF_HARM,
    "self-harm/instructions": _SELF_HARM,
    "harassment/threatening": _THREAT,
    "hate/threatening": _THREAT,
    "illicit/violent": _THREAT,
    "sexual": _GRAPHIC,
    "violence/graphic": _GRAPHIC,
    "harassment": _GENERAL,
    "hate": _GENERAL,
    "illicit": _GENERAL,
    "violence": _GENERAL,
}


def validate_thresholds(raw: dict[str, Any]) -> Thresholds:
    """Parse editable thresholds ({cat: {low, high}}), enforcing 0 <= low < high <= 1."""
    out: Thresholds = {}
    for cat, v in raw.items():
        if cat not in DEFAULT_THRESHOLDS:
            raise ValueError(f"unknown category: {cat}")
        try:
            low, high = float(v["low"]), float(v["high"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"{cat}: needs numeric low and high") from exc
        if not 0 <= low < high <= 1:
            raise ValueError(f"{cat}: need 0 <= low < high <= 1")
        out[cat] = (low, high)
    return out


def effective_thresholds(overrides: dict[str, Any] | None) -> Thresholds:
    return {**DEFAULT_THRESHOLDS, **validate_thresholds(overrides or {})}


def band_for(scores: dict[str, float], thresholds: Thresholds) -> tuple[Band, list[str], list[str]]:
    """Return (band, categories >= high, categories >= low).

    Categories the API adds later but we have no thresholds for use the general pair.
    """
    high_hits: list[str] = []
    low_hits: list[str] = []
    for cat, score in scores.items():
        low, high = thresholds.get(cat, _GENERAL)
        if score >= high:
            high_hits.append(cat)
        if score >= low:
            low_hits.append(cat)
    if high_hits:
        return "harmful", high_hits, low_hits
    if low_hits:
        return "inconclusive", high_hits, low_hits
    return "safe", high_hits, low_hits
