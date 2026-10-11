"""Shared aggregate evaluation metrics and explicit promotion gates; no runtime dependencies."""

from typing import Any


def metrics(rows: list[dict[str, Any]], field: str) -> dict[str, Any]:
    harmful = sum(r["human"] == "harmful" for r in rows)
    safe = len(rows) - harmful
    tp = sum(r["human"] == "harmful" and r[field] == "harmful" for r in rows)
    fp = sum(r["human"] == "safe" and r[field] == "harmful" for r in rows)
    misses = sum(r["human"] == "harmful" and r[field] == "safe" for r in rows)
    return {
        "samples": len(rows),
        "harmful": harmful,
        "safe": safe,
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": misses,
        "review": sum(r[field] == "review" for r in rows),
        "precision": tp / (tp + fp) if tp + fp else None,
        "harmful_detection_rate": tp / harmful if harmful else None,
    }


def promotion_gate(report: dict[str, Any]) -> dict[str, Any]:
    reasons = []
    if report.get("source") != "held_out_human_reviews":
        reasons.append("Synthetic checks cannot justify production promotion.")
    baseline, candidate = report["baseline"], report["candidate"]
    if candidate["samples"] < 100 or min(candidate["harmful"], candidate["safe"]) < 30:
        reasons.append(
            "At least 100 held-out labels, including 30 harmful and 30 safe, are required."
        )
    if report.get("failures") or report.get("pending"):
        reasons.append("Evaluation has failed or incomplete model requests.")
    if (
        candidate["false_negative"] > baseline["false_negative"]
        or candidate["false_positive"] > baseline["false_positive"]
    ):
        reasons.append("The candidate introduces additional missed harm or false alerts.")
    if (candidate["precision"] or 0) < 0.95 or (candidate["harmful_detection_rate"] or 0) < 0.95:
        reasons.append("Candidate precision and harmful detection must both reach 95 percent.")
    if candidate["false_positive"] >= baseline["false_positive"] and (
        candidate["harmful_detection_rate"] or 0
    ) <= (baseline["harmful_detection_rate"] or 0):
        reasons.append("The candidate must demonstrate improvement over the baseline.")
    return {"eligible": not reasons, "reasons": reasons, "automatic_promotion": False}
