"""Bounded synthetic evaluation and explicit promotion gate; no conversation exports."""

import asyncio
import hashlib
import time
from datetime import UTC, datetime
from typing import Any

from app.classify.community import guidance, load_pack, public_manifest
from app.classify.ollama import OllamaModerator
from app.classify.prompt import prompt_fingerprint
from app.classify.quality import QUALITY_POLICY, paired_comparison
from app.classify.quality import metrics as metrics
from app.classify.quality import promotion_gate as promotion_gate
from app.classify.thresholds import DEFAULT_THRESHOLDS, band_for
from app.config import get_settings
from app.db.models import Job, Setting
from app.jobs.handlers import Deps
from app.jobs.queue import ClaimedJob, DeferredError, ensure_owned

RESULT_KEY = "internal.learning_evaluation"


async def evaluate_community(
    model: str,
    base_url: str,
    *,
    checkpoint: dict[str, Any] | None = None,
    request_timeout: float = 30,
) -> dict[str, Any]:
    client = OllamaModerator(base_url, model)
    rows: list[dict[str, Any]] = [] if checkpoint is None else checkpoint.setdefault("rows", [])
    failures = 0
    started = time.monotonic()
    pack = await asyncio.to_thread(load_pack)
    attempts: dict[str, int] = {} if checkpoint is None else checkpoint.setdefault("attempts", {})
    errors: dict[str, int] = {} if checkpoint is None else checkpoint.setdefault("errors", {})
    completed = {r.get("case_id") for r in rows}
    cases = [
        e for e in pack["evaluation"] if e["id"] not in completed and attempts.get(e["id"], 0) < 3
    ]
    if checkpoint is not None:
        cases = sorted(cases, key=lambda e: attempts.get(e["id"], 0))[:1]
    try:
        for example in cases:
            if time.monotonic() - started > 300:
                failures += len(pack["evaluation"]) - len(rows) - failures
                break
            try:
                stage = "baseline"
                attempts[example["id"]] = attempts.get(example["id"], 0) + 1
                baseline = await asyncio.wait_for(
                    client.moderate(model, example["content"]), request_timeout
                )
                stage = "candidate"
                candidate = await asyncio.wait_for(
                    client.moderate(
                        model, example["content"], examples=guidance(example["content"])
                    ),
                    request_timeout,
                )
                band0, _, _ = band_for(baseline.scores, DEFAULT_THRESHOLDS)
                band1, _, _ = band_for(candidate.scores, DEFAULT_THRESHOLDS)
                rows.append(
                    {
                        "case_id": example["id"],
                        "human": example["verdict"],
                        "language": example["language"],
                        "baseline": "review" if band0 == "inconclusive" else band0,
                        "candidate": "review" if band1 == "inconclusive" else band1,
                        "expected_categories": example["categories"],
                        "baseline_categories": baseline.scores,
                        "candidate_categories": candidate.scores,
                    }
                )
            except Exception as exc:
                failures += 1
                key = stage + ":" + type(exc).__name__
                errors[key] = errors.get(key, 0) + 1
        completed = {r.get("case_id") for r in rows}
        pending = sum(
            e["id"] not in completed and attempts.get(e["id"], 0) < 3 for e in pack["evaluation"]
        )
        if checkpoint is not None:
            failures = len(pack["evaluation"]) - len(rows) - pending
        report: dict[str, Any] = {
            "source": "synthetic",
            "quality_policy": QUALITY_POLICY,
            "prompt_sha256": prompt_fingerprint(),
            "model": model,
            "pack": public_manifest(),
            "checked_at": datetime.now(UTC).isoformat(),
            "evaluated": len(rows),
            "expected": len(pack["evaluation"]),
            "pending": pending if checkpoint is not None else 0,
            "request_errors": errors,
            "failures": failures,
            "latency_ms": int((time.monotonic() - started) * 1000),
            "baseline": metrics(rows, "baseline"),
            "candidate": metrics(rows, "candidate"),
            "paired": paired_comparison(rows),
            "languages": {
                lang: {
                    field: metrics([r for r in rows if r["language"] == lang], field)
                    for field in ("baseline", "candidate")
                }
                for lang in ("he", "en")
            },
            "categories": {
                cat: {
                    "labelled": sum(cat in r["expected_categories"] for r in rows),
                    **{
                        field: {
                            "detected": sum(
                                cat in r["expected_categories"]
                                and r[field + "_categories"][cat] >= threshold[1]
                                for r in rows
                            ),
                            "false_positive": sum(
                                r["human"] == "safe"
                                and r[field + "_categories"][cat] >= threshold[1]
                                for r in rows
                            ),
                        }
                        for field in ("baseline", "candidate")
                    },
                }
                for cat, threshold in DEFAULT_THRESHOLDS.items()
            },
            "weights_updated": False,
            "user_data_exported": False,
        }
        report["promotion"] = promotion_gate(report)
        return report
    finally:
        await client.aclose()


async def evaluate_job(job: ClaimedJob, deps: Deps) -> None:
    cfg = get_settings()
    if cfg.classification_provider != "ollama":
        report = {"error": "Learning evaluation requires Ollama.", "weights_updated": False}
    else:
        if job.payload.get("source") == "held_out_human_reviews":
            from app.classify.benchmark_learning import evaluate

            report = await evaluate(200, emit=False)
        else:
            fingerprint = hashlib.sha256(
                (
                    cfg.ollama_model
                    + cfg.ollama_base_url
                    + str(public_manifest())
                    + prompt_fingerprint()
                    + QUALITY_POLICY
                ).encode()
            ).hexdigest()
            checkpoint = job.payload.get("evaluation_checkpoint", {})
            if checkpoint.get("fingerprint") != fingerprint:
                checkpoint = {"fingerprint": fingerprint}
            timeout = min(float(cfg.job_timeout_seconds), 570.0)
            report = await evaluate_community(
                cfg.ollama_model,
                cfg.ollama_base_url,
                checkpoint=checkpoint,
                request_timeout=max(0.1, min(120.0, (timeout - 10) / 2)),
            )
            job.payload["evaluation_checkpoint"] = checkpoint
    async with deps.session_factory() as db:
        await ensure_owned(db, job)
        row = await db.get(Setting, RESULT_KEY)
        if row is None:
            db.add(Setting(key=RESULT_KEY, value=report))
        else:
            row.value = report
        stored = await db.get(Job, job.id)
        if stored is not None:
            stored.payload = dict(job.payload)
        await db.commit()
    if report.get("pending"):
        raise DeferredError(
            "Continuing learning evaluation", 1, reason="Continuing learning evaluation"
        )
