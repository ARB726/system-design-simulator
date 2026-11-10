"""Turn raw simulation output into per-second timelines, a summary, and plain-English findings."""
from __future__ import annotations

import math
from typing import Dict, List

import numpy as np
import pandas as pd

from .config import EVENT_KINDS, app_capacity_rps, expected_utilization, replicas_needed
from .engine import SimResult

TIER_LABEL = {
    "app": "App tier",
    "cache": "Cache",
    "db_primary": "DB primary",
    "db_replicas": "DB read replicas",
}
FAIL_KINDS = ["dropped", "timeout", "error", "incomplete"]


def health(util: float) -> str:
    """Status band used for colors and labels (always paired with an icon + word in the UI)."""
    if util >= 0.95:
        return "critical"
    if util >= 0.85:
        return "serious"
    if util >= 0.70:
        return "warning"
    return "good"


def tiers_present(res: SimResult) -> List[str]:
    return [t for t in TIER_LABEL if f"util_{t}" in res.series.columns]


# ---------------------------------------------------------------- timeline
def timeline(res: SimResult, bin_s: float = 1.0) -> pd.DataFrame:
    dur = res.cfg.workload.duration_s
    idx = pd.Index(np.arange(0, dur, bin_s), name="t")
    req = res.requests.assign(bin=(res.requests.t // bin_s) * bin_s)
    g = req.groupby("bin")

    tl = pd.DataFrame(index=idx)
    tl["offered_rps"] = g.size().reindex(idx, fill_value=0) / bin_s
    tl["served_rps"] = req[req.status == "ok"].groupby("bin").size().reindex(idx, fill_value=0) / bin_s
    for k in FAIL_KINDS:
        tl[f"{k}_rps"] = req[req.status == k].groupby("bin").size().reindex(idx, fill_value=0) / bin_s
    q = g.eff_ms.quantile([0.5, 0.95, 0.99]).unstack().reindex(idx)
    tl["p50"], tl["p95"], tl["p99"] = q[0.5], q[0.95], q[0.99]

    ser = res.series.assign(bin=(res.series.t // bin_s) * bin_s)
    sg = ser.drop(columns="t").groupby("bin").mean().reindex(idx)
    return tl.join(sg)


# ---------------------------------------------------------------- summary
def summarize(res: SimResult, tl: pd.DataFrame | None = None) -> Dict:
    cfg = res.cfg
    w = cfg.workload
    tl = timeline(res) if tl is None else tl
    r = res.requests[res.requests.t >= w.warmup_s]
    span = max(w.duration_s - w.warmup_s, 1e-9)
    steady = tl[tl.index >= w.warmup_s]

    n = len(r)
    ok = r[r.status == "ok"]
    s = {
        "offered_rps": n / span,
        "served_rps": len(ok) / span,
        "success_rate": len(ok) / n if n else 1.0,
        "p50_ms": float(r.eff_ms.quantile(0.50)) if n else 0.0,
        "p95_ms": float(r.eff_ms.quantile(0.95)) if n else 0.0,
        "p99_ms": float(r.eff_ms.quantile(0.99)) if n else 0.0,
        "fail": {k: int((r.status == k).sum()) for k in FAIL_KINDS},
    }

    reads = r[r.is_read]
    hit_known = reads.hit.dropna()
    s["measured_hit_rate"] = float(hit_known.mean()) if len(hit_known) else None
    miss = 1.0 - s["measured_hit_rate"] if s["measured_hit_rate"] is not None else 1.0
    s["flows"] = {
        "offered": s["offered_rps"],
        "reads": len(reads) / span,
        "writes": (n - len(reads)) / span,
        "db_reads": len(reads) / span * miss,
    }

    tiers = {}
    for t in tiers_present(res):
        u = steady[f"util_{t}"].dropna()
        q = steady[f"q_{t}"].dropna()
        p90 = float(u.quantile(0.90)) if len(u) else 0.0
        tiers[t] = {
            "mean_util": float(u.mean()) if len(u) else 0.0,
            "p90_util": p90,
            "peak_util": float(u.max()) if len(u) else 0.0,
            "peak_queue": float(q.max()) if len(q) else 0.0,
            "status": health(p90),
        }
    s["tiers"] = tiers
    s["bottleneck"] = max(tiers, key=lambda k: tiers[k]["p90_util"]) if tiers else None
    s["expected"] = expected_utilization(cfg)
    return s


# ---------------------------------------------------------------- findings
def _window_mean(tl: pd.DataFrame, col: str, a: float, b: float) -> float:
    m = tl[(tl.index >= a) & (tl.index < b)][col].dropna()
    return float(m.mean()) if len(m) else float("nan")


def diagnose(res: SimResult, s: Dict, tl: pd.DataFrame) -> List[Dict]:
    """Deterministic, rule-based findings. Facts come from the simulator, not from an LLM."""
    cfg = res.cfg
    a, d, w = cfg.app, cfg.db, cfg.workload
    out: List[Dict] = []
    add = lambda level, title, detail: out.append({"level": level, "title": title, "detail": detail})

    fail = s["fail"]
    total_fail = sum(fail.values())
    if s["success_rate"] < 0.99:
        parts = [f"{v:,} {k}" for k, v in fail.items() if v]
        add("critical" if s["success_rate"] < 0.95 else "serious",
            f"{1 - s['success_rate']:.1%} of requests failed",
            "Breakdown: " + ", ".join(parts) + ". Timeouts mean requests waited too long; drops mean "
            "a queue overflowed; errors mean a replica died mid-request.")

    peak_offered = float(tl.offered_rps.rolling(3, min_periods=1).mean().max())
    for t, st in s["tiers"].items():
        if st["p90_util"] < 0.85:
            continue
        sat = st["peak_util"] >= 0.99
        head = f"{TIER_LABEL[t]} {'is saturated' if sat else 'runs hot'} " \
               f"(90th-percentile utilization {st['p90_util']:.0%}, peak queue {st['peak_queue']:.0f})"
        if t == "app":
            cap = app_capacity_rps(cfg)
            need = replicas_needed(peak_offered, a.latency_ms, a.workers, 0.7)
            add("critical" if sat else "serious", head,
                f"Capacity is replicas x workers / latency = {a.replicas} x {a.workers} / "
                f"{a.latency_ms:g} ms = {cap:,.0f} rps, against a peak of {peak_offered:,.0f} rps. "
                f"Horizontal fix: about {need} replicas keeps that peak near 70% utilization.")
        elif t == "db_primary":
            wr = s["flows"]["writes"] * d.write_ms / 1000.0 / d.workers
            rd = s["flows"]["db_reads"] * d.read_ms / 1000.0 / d.workers if d.read_replicas == 0 else 0.0
            if wr >= rd:
                add("critical" if sat else "serious", head,
                    "Most of its load is writes. Read replicas and caches do not help here, because every "
                    "write must go through the primary. Options: batch or queue writes, shard by key, "
                    "or reduce per-write latency.")
            else:
                add("critical" if sat else "serious", head,
                    "Most of its load is reads that missed the cache. Options: raise the hit rate, add read "
                    "replicas, or add request coalescing so one miss does not become a thousand.")
        elif t == "db_replicas":
            add("critical" if sat else "serious", head,
                "Read replicas are saturated. Add more replicas or improve the cache hit rate.")
        else:
            add("serious", head, "Add cache capacity (workers or shards).")

    for e in cfg.events:
        a0, b0 = e.start_s, e.end_s
        before = (max(0, a0 - 15), a0)
        tag = f"During '{e.label()}'"
        if e.kind == "cold_cache" and "util_db_primary" in tl.columns:
            u0 = _window_mean(tl, "util_db_primary", *before)
            u1 = _window_mean(tl, "util_db_primary", a0, b0)
            add("serious" if u1 >= 0.85 else "info", f"{tag}, database load jumped",
                f"Primary utilization went from {u0:.0%} to {u1:.0%}. A high hit rate hides how little "
                f"capacity the database really has.")
        elif e.kind == "traffic_spike":
            u0 = _window_mean(tl, "util_app", *before)
            u1 = _window_mean(tl, "util_app", a0, b0)
            add("info", f"{tag}, app utilization went {u0:.0%} to {u1:.0%}",
                f"Failure rate in the window: "
                f"{_window_mean(tl, 'timeout_rps', a0, b0) + _window_mean(tl, 'dropped_rps', a0, b0):,.0f} req/s "
                f"timed out or dropped.")
        elif e.kind == "kill_app":
            surv = max(a.replicas - int(e.magnitude), 0)
            add("info", f"{tag}, {surv} of {a.replicas} replicas survived",
                f"Surviving capacity: {surv * a.workers * 1000 / a.latency_ms:,.0f} rps versus "
                f"{w.rps:,.0f} rps offered.")

    if not any(o["level"] in ("critical", "serious") for o in out):
        cap = app_capacity_rps(cfg)
        add("good", "The design holds",
            f"Success rate {s['success_rate']:.2%}, p95 {s['p95_ms']:.0f} ms. App tier could absorb roughly "
            f"{cap / max(peak_offered, 1):.1f}x the peak load before saturating.")

    pred = s["expected"]
    worst = max(pred, key=pred.get)
    if pred[worst] >= 1.0 and s["tiers"].get(worst, {}).get("mean_util", 0) > 0:
        add("info", "Napkin math already predicted this",
            f"Steady-state demand on {TIER_LABEL[worst]} is {pred[worst]:.0%} of capacity before any event.")
    return out
