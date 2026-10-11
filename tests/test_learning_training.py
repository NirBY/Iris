import json

import pytest

from app.classify.community import guidance, load_pack
from app.classify.thresholds import DEFAULT_THRESHOLDS
from scripts.evaluate_learning_adapter import parse_scores, summarize_predictions
from scripts.prepare_learning_model import prepare, records_for
from scripts.train_learning_adapter import validate


def test_every_category_has_synthetic_coverage_in_each_language_and_split():
    for split in ("examples", "evaluation"):
        for language in ("he", "en"):
            cases = [c for c in load_pack()[split] if c["language"] == language]
            assert {category for c in cases for category in c["categories"]} == set(
                DEFAULT_THRESHOLDS
            )
            assert sum(c["verdict"] == "safe" for c in cases) >= 6
    for text in ("sexual pictures from a minor", "קטין ותמונות מיניות"):
        selected = guidance(text)
        assert len(selected) == 6
        assert sum(c["verdict"] == "safe" for c in selected) == 3
        assert any("sexual/minors" in c["human_categories"] for c in selected)


def test_local_base_weights_and_tokenizer_cannot_change_silently(tmp_path):
    base = tmp_path / "base"
    base.mkdir()
    (base / "config.json").write_text("{}")
    weights = base / "model.safetensors"
    weights.write_bytes(b"initial weights")
    data = tmp_path / "dataset"
    prepare(data, str(base), "local-v1")
    assert validate(data)["base_identity"]["kind"] == "local"
    weights.write_bytes(b"changed weights")
    with pytest.raises(ValueError, match="Base model or tokenizer changed"):
        validate(data)


def test_remote_training_plan_requires_an_immutable_commit(tmp_path):
    with pytest.raises(ValueError, match="full pinned commit"):
        prepare(tmp_path, "example/model", "main")
    assert prepare(tmp_path, "example/model", "a" * 40)["base_identity"]["commit"] == "a" * 40


def test_generated_output_quality_checks_never_promote_synthetic_or_invalid_output():
    answers = [r["messages"][-1]["content"] for r in records_for(load_pack(), "evaluation")]
    report = summarize_predictions(answers, answers)
    assert report["evaluated"] == len(answers) and report["failures"] == 0
    assert report["candidate"]["false_negative"] == 0
    assert not report["promotion"]["eligible"] and not report["publishable_weights"]
    candidate = list(answers)
    candidate[0] = "private diagnostic must never enter reports"
    report = summarize_predictions(answers, candidate)
    assert report["failures"] == 1 and report["invalid_outputs"]["candidate"] == 1
    assert report["candidate"]["samples"] == len(answers) - 1
    assert "private diagnostic" not in json.dumps(report)
    assert not report["promotion"]["eligible"]


@pytest.mark.parametrize("bad", [True, -1, 1.1, float("nan"), "0.5"])
def test_malformed_scores_are_not_safe_verdicts(bad):
    scores = dict.fromkeys(DEFAULT_THRESHOLDS, 0)
    scores["violence"] = bad
    with pytest.raises(ValueError):
        parse_scores(json.dumps(scores))
