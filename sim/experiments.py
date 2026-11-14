"""Batch experiments built on the engine: load sweep, scaling sweep, and M/M/c validation."""
from __future__ import annotations

from typing import Callable, Iterable, Optional
import statistics

import pandas as pd

from .config import AppTier, Config, Workload, config_from_dict, monthly_cost
from .batch import summaries
from .engine import SimResult, run, run_summary
from .theory import mmc_mean_response

Progress = Optional[Callable[[float, str], None]]


def _clone(cfg: Config) -> Config:
    return config_from_dict(cfg.to_dict())


def _quick(res: SimResult) -> dict:
    """Steady-state numbers for one run, cheaper than the full summary."""
    w = res.cfg.workload
    r = res.requests[res.requests.t >= w.warmup_s]
    span = max(w.duration_s - w.warmup_s, 1e-9)
    ok = r[r.status == "ok"]
    return {
        "offered_rps": len(r) / span,
        "served_rps": len(ok) / span,
        "success_rate": len(ok) / len(r) if len(r) else 1.0,
        "p50_ms": float(r.eff_ms.quantile(0.5)) if len(r) else 0.0,
        "p95_ms": float(r.eff_ms.quantile(0.95)) if len(r) else 0.0,
        "p99_ms": float(r.eff_ms.quantile(0.99)) if len(r) else 0.0,
    }


def _steady_copy(cfg: Config, duration_s: float, warmup_s: float) -> Config:
    c = _clone(cfg)
    c.events = []                       # sweeps measure steady state, not chaos
    c.workload.duration_s = duration_s
    c.workload.warmup_s = warmup_s
    return c


def sweep_load(cfg: Config, rps_values: Iterable[float], duration_s: float = 25.0,
               warmup_s: float = 5.0, progress: Progress = None, workers: int = 1) -> pd.DataFrame:
    """Raise offered load and watch throughput flatten and latency blow up (the 'knee')."""
    vals = list(rps_values)
    configs = []
    for rps in vals:
        c = _steady_copy(cfg, duration_s, warmup_s)
        c.workload.rps = float(rps)
        configs.append(c)
    metrics = summaries(configs, workers=workers, progress=progress, runner=run_summary)
    rows = [{"target_rps": float(rps), **result} for rps, result in zip(vals, metrics)]
    return pd.DataFrame(rows)


def sweep_replicas(cfg: Config, replica_values: Iterable[int], strategies: Iterable[str],
                   duration_s: float = 25.0, warmup_s: float = 5.0, progress: Progress = None,
                   workers: int = 1) -> pd.DataFrame:
    """Fixed load, vary the number of app replicas and the load-balancing strategy."""
    reps, strats = list(replica_values), list(strategies)
    configs, labels = [], []
    for strat in strats:
        for n in reps:
            c = _steady_copy(cfg, duration_s, warmup_s)
            c.app.replicas, c.app.lb_strategy = int(n), strat
            configs.append(c)
            labels.append(dict(replicas=int(n), strategy=strat))
    metrics = summaries(configs, workers=workers, progress=progress, runner=run_summary)
    rows = [{**label, **result} for label, result in zip(labels, metrics)]
    return pd.DataFrame(rows)


def compare_seeds(baseline: Config, candidate: Config, seeds, *, workers=1, progress=None):
    """Paired runs report model variability; no production-accuracy claim or CI."""
    try:
        seeds = list(seeds)
    except TypeError as exc:
        raise ValueError("Choose 3 to 10 distinct integer seeds.") from exc
    if not 3 <= len(seeds) <= 10:
        raise ValueError("Choose 3 to 10 distinct seeds.")
    if any(isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= 2**63 - 1 for seed in seeds):
        raise ValueError("Seeds must be integers between 0 and 2**63 - 1.")
    if len(set(seeds)) != len(seeds):
        raise ValueError("Choose 3 to 10 distinct seeds.")
    if baseline.workload != candidate.workload or baseline.events != candidate.events or baseline.app_only != candidate.app_only:
        raise ValueError("Paired comparisons require identical workloads, failure events, and model mode.")
    configs, labels = [], []
    for seed in seeds:
        for label, cfg in (("Baseline", baseline), ("Candidate", candidate)):
            c = _clone(cfg)
            c.seed = seed
            configs.append(c)
            labels.append(dict(seed=seed, design=label))
    metrics = summaries(configs, workers=workers, progress=progress, runner=run_summary)
    rows = [{**label, **result} for label, result in zip(labels, metrics)]
    def stats(values):
        return dict(mean=statistics.mean(values), sd=statistics.stdev(values),
                    minimum=min(values), maximum=max(values))
    keys = ("served_rps", "success_rate", "p95_ms", "p99_ms")
    aggregates, deltas = [], []
    for key in keys:
        a = [row[key] for row in rows if row["design"] == "Baseline"]
        b = [row[key] for row in rows if row["design"] == "Candidate"]
        for label, values in (("Baseline", a), ("Candidate", b)):
            aggregates.append(dict(design=label, metric=key, **stats(values)))
        diff = [bv - av for av, bv in zip(a, b)]
        improved = sum(d < 0 if key.endswith("_ms") else d > 0 for d in diff)
        deltas.append(dict(metric=key, **stats(diff), improved_seeds=improved,
                           tied_seeds=sum(d == 0 for d in diff), seeds=len(seeds)))
    return dict(rows=rows, aggregates=aggregates, deltas=deltas, seeds=seeds,
                baseline_config=baseline.to_dict(), candidate_config=candidate.to_dict(),
                baseline_cost=monthly_cost(baseline), candidate_cost=monthly_cost(candidate),
                caution="Variation across seeds describes uncertainty within this model. "
                        "It does not establish production accuracy or statistical significance. "
                        "Each seed is shared across designs; changed routing can consume random numbers differently.")


def validate_mmc(c: int = 4, mu: float = 50.0, rhos=(0.3, 0.5, 0.7, 0.8, 0.9), duration_s: float = 300.0,
                 warmup_s: float = 20.0, seed: int = 7, progress: Progress = None, backend: str = "simpy") -> pd.DataFrame:
    """Compare simulated mean response time with the Erlang C formula for an M/M/c queue."""
    if backend not in ("simpy", "cpp"):
        raise ValueError("Unknown validation backend.")
    rhos = list(rhos)
    if not 1 <= len(rhos) <= 12:
        raise ValueError("At most 12 validation points are allowed.")
    rows = []
    for i, rho in enumerate(rhos):
        lam = rho * c * mu
        cfg = Config(
            name="M/M/c validation",
            app=AppTier(replicas=1, workers=c, latency_ms=1000.0 / mu, lb_strategy="shared", max_queue=None),
            workload=Workload(rps=lam, read_ratio=1.0, duration_s=duration_s, timeout_ms=None, warmup_s=warmup_s),
            seed=seed + i, app_only=True,
        )
        if backend == "cpp":
            from .native import simulate_mmc
            result = simulate_mmc(c, lam, mu, duration_s, warmup_s, seed + i)
            sim_ms, requests = result["mean_response_s"] * 1000.0, result["requests"]
        else:
            res = run(cfg)
            r = res.requests[res.requests.t >= warmup_s]
            sim_ms, requests = float(r.latency_ms.mean()), len(r)
        th_ms = mmc_mean_response(lam, mu, c) * 1000.0
        rows.append({"utilization": rho, "arrival_rps": lam, "simulated_ms": sim_ms,
                     "theory_ms": th_ms, "error_pct": (sim_ms / th_ms - 1.0) * 100.0, "requests": requests})
        if progress:
            progress((i + 1) / len(list(rhos)), f"utilization {rho:.0%}")
    return pd.DataFrame(rows)
