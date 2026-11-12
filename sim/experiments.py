"""Batch experiments built on the engine: load sweep, scaling sweep, and M/M/c validation."""
from __future__ import annotations

from typing import Callable, Iterable, Optional

import pandas as pd

from .config import AppTier, Config, Workload, config_from_dict
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
               warmup_s: float = 5.0, progress: Progress = None) -> pd.DataFrame:
    """Raise offered load and watch throughput flatten and latency blow up (the 'knee')."""
    vals = list(rps_values)
    rows = []
    for i, rps in enumerate(vals):
        c = _steady_copy(cfg, duration_s, warmup_s)
        c.workload.rps = float(rps)
        rows.append({"target_rps": float(rps), **run_summary(c)})
        if progress:
            progress((i + 1) / len(vals), f"{rps:,.0f} rps")
    return pd.DataFrame(rows)


def sweep_replicas(cfg: Config, replica_values: Iterable[int], strategies: Iterable[str],
                   duration_s: float = 25.0, warmup_s: float = 5.0, progress: Progress = None) -> pd.DataFrame:
    """Fixed load, vary the number of app replicas and the load-balancing strategy."""
    reps, strats = list(replica_values), list(strategies)
    total, done, rows = len(reps) * len(strats), 0, []
    for strat in strats:
        for n in reps:
            c = _steady_copy(cfg, duration_s, warmup_s)
            c.app.replicas, c.app.lb_strategy = int(n), strat
            rows.append({"replicas": int(n), "strategy": strat, **run_summary(c)})
            done += 1
            if progress:
                progress(done / total, f"{n} replicas, {strat}")
    return pd.DataFrame(rows)


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
