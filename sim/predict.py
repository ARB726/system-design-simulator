"""Predict-then-run: score how well a student's napkin math matched the simulator.

The student predicts four things before running: which tier is the bottleneck, how busy it is, which latency
bucket p95 lands in, and whether the design holds. Utilization and latency are scored against a *baseline* run
without chaos events (that is what napkin math describes); "holds" is scored against the full run.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from .analysis import TIER_LABEL

BUCKETS = ["under 50 ms", "50 to 150 ms", "150 to 500 ms", "over 500 ms"]
_EDGES = [50.0, 150.0, 500.0]

POINTS = dict(bottleneck=40, util=30, p95=20, holds=10)
TIE_BAND = 0.05           # tiers within 5 percentage points of the busiest all count as "the bottleneck"
UTIL_TOLERANCE = 0.30     # utilization guess loses all points at 30 points of error


@dataclass
class Prediction:
    bottleneck: str                 # tier key, e.g. "db_primary"
    utilization: float              # 0..1+, of that tier
    p95_bucket: int                 # index into BUCKETS
    holds: bool


def bucket_of(ms: float) -> int:
    for i, e in enumerate(_EDGES):
        if ms < e:
            return i
    return len(_EDGES)


def truth_from_summary(s: Dict) -> Dict:
    """Ground truth from a (baseline) simulation summary."""
    tiers = s["tiers"]
    means = {t: v["mean_util"] for t, v in tiers.items()}
    top = max(means, key=means.get) if means else None
    accepted: List[str] = [t for t, u in means.items() if top and u >= means[top] - TIE_BAND]
    return dict(bottleneck=top, accepted=accepted, utilization=means.get(top, 0.0),
                p95_ms=s["p95_ms"], p95_bucket=bucket_of(s["p95_ms"]))


def score_prediction(pred: Prediction, baseline_summary: Dict, holds_truth: bool) -> Dict:
    t = truth_from_summary(baseline_summary)
    parts = {}
    parts["bottleneck"] = POINTS["bottleneck"] if pred.bottleneck in t["accepted"] else 0
    err = abs(pred.utilization - t["utilization"])
    parts["util"] = round(POINTS["util"] * max(0.0, 1.0 - err / UTIL_TOLERANCE), 1)
    d = abs(pred.p95_bucket - t["p95_bucket"])
    parts["p95"] = POINTS["p95"] if d == 0 else (POINTS["p95"] // 2 if d == 1 else 0)
    parts["holds"] = POINTS["holds"] if pred.holds == holds_truth else 0
    total = round(sum(parts.values()), 1)

    notes = []
    names = {k: TIER_LABEL.get(k, k) for k in list(t["accepted"]) + [pred.bottleneck]}
    if parts["bottleneck"] == 0:
        notes.append(f"You picked {names[pred.bottleneck]}; the busiest tier was "
                     f"{TIER_LABEL.get(t['bottleneck'], t['bottleneck'])} at {t['utilization']:.0%}.")
    if err > 0.10:
        notes.append(f"Your utilization guess was {pred.utilization:.0%}; actual {t['utilization']:.0%}. "
                     f"Recheck the arrival rate that actually reaches that tier (CDN hits and cache hits "
                     f"never get there).")
    if d:
        notes.append(f"p95 landed in '{BUCKETS[t['p95_bucket']]}', you said '{BUCKETS[pred.p95_bucket]}'.")
    if parts["holds"] == 0:
        notes.append("The design " + ("held" if holds_truth else "did not hold") + " under the full scenario.")
    return dict(total=total, parts=parts, truth=t, notes=notes, max_points=sum(POINTS.values()))
