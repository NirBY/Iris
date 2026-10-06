import pytest

from app.classify.thresholds import (
    DEFAULT_THRESHOLDS,
    band_for,
    effective_thresholds,
    validate_thresholds,
)

T = DEFAULT_THRESHOLDS


@pytest.mark.parametrize(
    ("cat", "score", "band"),
    [
        ("violence", 0.19999, "safe"),
        ("violence", 0.20, "inconclusive"),  # == low
        ("violence", 0.69999, "inconclusive"),
        ("violence", 0.70, "harmful"),  # == high
        ("sexual/minors", 0.049, "safe"),
        ("sexual/minors", 0.05, "inconclusive"),
        ("sexual/minors", 0.30, "harmful"),
        ("self-harm/intent", 0.10, "inconclusive"),
        ("self-harm/intent", 0.40, "harmful"),
        ("harassment/threatening", 0.15, "inconclusive"),
        ("harassment/threatening", 0.50, "harmful"),
        ("sexual", 0.60, "harmful"),
        ("violence/graphic", 0.14, "safe"),
    ],
)
def test_banding_edges(cat: str, score: float, band: str) -> None:
    assert band_for({cat: score}, T)[0] == band


def test_any_high_wins_over_other_inconclusive() -> None:
    band, high, low = band_for({"violence": 0.3, "hate": 0.9}, T)
    assert band == "harmful" and high == ["hate"] and set(low) == {"violence", "hate"}


def test_unknown_category_uses_general_pair() -> None:
    assert band_for({"brand-new": 0.25}, T)[0] == "inconclusive"
    assert band_for({"brand-new": 0.05}, T)[0] == "safe"


def test_all_thirteen_categories_have_defaults() -> None:
    assert len(T) == 13


def test_overrides_merge_and_validate() -> None:
    eff = effective_thresholds({"violence": {"low": 0.5, "high": 0.9}})
    assert eff["violence"] == (0.5, 0.9) and eff["hate"] == T["hate"]
    for bad in (
        {"violence": {"low": 0.5, "high": 0.5}},
        {"violence": {"low": -1, "high": 0.5}},
        {"violence": {"low": 0.1, "high": 1.5}},
        {"nope": {"low": 0.1, "high": 0.2}},
        {"violence": {"low": "x", "high": 0.2}},
        {"violence": {}},
    ):
        with pytest.raises(ValueError):
            validate_thresholds(bad)
