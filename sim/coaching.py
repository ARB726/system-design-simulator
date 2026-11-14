"""Measured pressure windows and single-variable experiment proposals."""
from __future__ import annotations

import math

from .analysis import TIER_LABEL
from .config import config_from_dict
from .limits import validate_config


def pressure_evidence(res, tl, summary):
    """Locate a three-bin pressure window per tier, using post-warmup samples."""
    rows = []
    bin_width = float(tl.index[1] - tl.index[0]) if len(tl.index) > 1 else res.cfg.workload.duration_s
    for tier in summary["tiers"]:
        util, queue = f"util_{tier}", f"q_{tier}"
        samples = tl.loc[tl.index >= res.cfg.workload.warmup_s, [util, queue]].dropna()
        if samples.empty:
            continue
        size = min(3, len(samples))
        rolling = samples[util].rolling(size, min_periods=size).mean()
        queued = samples[queue].rolling(size, min_periods=size).mean()
        peak = max(rolling.dropna().index, key=lambda t: (float(rolling.loc[t]), float(queued.loc[t])))
        end = samples.index.get_loc(peak)
        window = samples.iloc[max(0, end - 2):end + 1]
        start_s, end_s = float(window.index[0]), min(float(window.index[-1]) + bin_width, res.cfg.workload.duration_s)
        requests = res.requests[(res.requests.t >= start_s) & (res.requests.t < end_s)]
        queue_growth = float(window[queue].iloc[-1] - window[queue].iloc[0])
        utilization = float(window[util].mean())
        rows.append(dict(tier=tier, label=TIER_LABEL[tier], start_s=start_s, end_s=end_s,
                         utilization=utilization, peak_queue=float(window[queue].max()),
                         queue_growth=queue_growth, requests=len(requests),
                         success_rate=float((requests.status == "ok").mean()) if len(requests) else None,
                         p95_ms=float(requests.eff_ms.quantile(.95)) if len(requests) else None,
                         constrained=utilization >= .85 and float(window[queue].max()) > 0))
    return sorted(rows, key=lambda row: (row["constrained"], row["utilization"]), reverse=True)


def suggest_experiment(cfg, evidence):
    """Change one capacity setting; this is a hypothesis, not a promised fix."""
    settings = {
        "app": ("app", "replicas", 1, 64),
        "cache": ("cache", "workers", 16, 1024),
        "db_primary": ("db", "workers", 4, 256),
        "db_replicas": ("db", "read_replicas", 1, 16),
        "queue": ("queue", "consumers", 4, 256),
    }
    for row in evidence:
        if not row["constrained"]:
            continue
        section, field, step, maximum = settings[row["tier"]]
        # More consumers cannot resolve a saturated primary.
        if row["tier"] == "queue" and any(r["tier"] == "db_primary" and r["constrained"] for r in evidence):
            section, field, step, maximum = settings["db_primary"]
        candidate = config_from_dict(cfg.to_dict())
        before = getattr(getattr(candidate, section), field)
        after = min(maximum, before + step)
        if before == after:
            continue
        setattr(getattr(candidate, section), field, after)
        validate_config(candidate)
        return dict(setting=f"{section}.{field}", before=before, after=after,
                    candidate=candidate.to_dict(),
                    hypothesis=f"Increasing {section}.{field} may relieve the measured pressure. "
                               "Compare latency, success, and cost with the workload and failures held fixed.")
    return None


def evidence_findings(res, tl, summary):
    findings = []
    for row in pressure_evidence(res, tl, summary):
        if not row["constrained"]:
            continue
        p95 = f"{row['p95_ms']:.0f} ms" if row["p95_ms"] is not None and math.isfinite(row["p95_ms"]) else "unavailable"
        queue = summary.get("queue")
        recovered = (row["tier"] in ("queue", "db_primary") and queue is not None
                     and summary["success_rate"] >= .99
                     and queue["end_depth"] <= .05 * res.cfg.queue.max_depth)
        findings.append(dict(level="info" if recovered else "serious",
                             title=f"Measured pressure: {row['label']}" + (" (burst recovered)" if recovered else ""),
                             detail=f"From {row['start_s']:g} to {row['end_s']:g} s, mean utilization was "
                                    f"{row['utilization']:.0%}, peak sampled queue {row['peak_queue']:.1f}, "
                                    f"and queue change {row['queue_growth']:+.1f}. Requests arriving in this "
                                    f"window had end-to-end p95 {p95}. This is evidence of pressure, "
                                    "not proof that this tier alone caused the latency.", evidence=row))
    return findings
