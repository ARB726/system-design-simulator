"""Challenge mode: a brief, a few knobs, hidden chaos checks, and a score against the cheapest passing design.

A challenge fixes the workload and the failure scenarios. The student only chooses *knob* values
(replica counts, cache, CDN, queue, shards...). The design is then graded by running every check in a
deterministic simulation (fixed seeds). The optimizer in `tools/optimize.py` runs offline and stores the
cheapest passing design in `data/optima.json`, so a student's cost can be compared with it.
"""
from __future__ import annotations

import itertools
import json
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .analysis import summarize, timeline
from .config import (AppTier, CacheTier, Config, DBTier, Event, QueueTier, Workload, config_from_dict,
                     expected_utilization, monthly_cost)
from .engine import Simulation

OPTIMA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "optima.json")

# ---------------------------------------------------------------- knobs
KNOB_LABELS = {
    "app_replicas": "App replicas",
    "app_workers": "Workers per replica",
    "cache": "Cache",
    "cdn": "CDN",
    "db_workers": "DB connections per node",
    "shards": "DB shards",
    "read_replicas": "Read replicas per shard",
    "queue": "Async write queue",
    "consumers": "Queue consumers",
}
KNOB_HELP = {
    "app_replicas": "Horizontal scaling: more copies of the stateless app tier.",
    "app_workers": "Concurrency inside each replica (threads / event-loop slots).",
    "cache": "Absorbs most reads before they reach the database.",
    "cdn": "Answers a share of reads at the edge, before the app tier.",
    "db_workers": "Connections (parallelism) per database node. Bigger nodes cost more.",
    "shards": "Split data by key across independent primaries. Divides write load.",
    "read_replicas": "Extra copies that serve reads. They do not help writes.",
    "queue": "Acknowledge writes immediately and apply them later. Trades freshness for speed.",
    "consumers": "Workers draining the queue into the database.",
}


@dataclass
class Check:
    name: str
    blurb: str                       # shown after grading (hidden before)
    events: List[Event]
    duration_s: float
    p99_ms: float
    min_success: float
    max_lag_s: Optional[float] = None
    seed: int = 1000

    def slo_text(self) -> str:
        s = f"p99 ≤ {self.p99_ms:g} ms, success ≥ {self.min_success:.1%}"
        if self.max_lag_s is not None:
            s += f", write lag ≤ {self.max_lag_s:g} s"
        return s


@dataclass
class Challenge:
    id: str
    title: str
    story: str
    base: Config
    knobs: Dict[str, list]           # knob -> allowed values (in order)
    checks: List[Check]
    budget: float                    # hard monthly cap, dollars
    hints: List[str] = field(default_factory=list)
    industry: str = ""

    @property
    def slo_text(self) -> str:
        c = self.checks[0]
        return c.slo_text()


# ---------------------------------------------------------------- designs
def default_design(ch: Challenge) -> Dict:
    b = ch.base
    d = dict(app_replicas=b.app.replicas, app_workers=b.app.workers, cache=b.cache.enabled, cdn=b.cdn.enabled,
             db_workers=b.db.workers, shards=b.db.shards, read_replicas=b.db.read_replicas,
             queue=b.queue.enabled, consumers=b.queue.consumers)
    # snap to the first allowed value when the base value is not in the grid
    for k, vals in ch.knobs.items():
        if d[k] not in vals:
            d[k] = vals[0]
    return d


def normalize(ch: Challenge, design: Dict) -> Dict:
    d = default_design(ch)
    d.update({k: v for k, v in design.items() if k in d})
    return d


def apply_design(base: Config, design: Dict) -> Config:
    cfg = config_from_dict(base.to_dict())
    cfg.app.replicas = int(design["app_replicas"])
    cfg.app.workers = int(design["app_workers"])
    cfg.cache.enabled = bool(design["cache"])
    cfg.cdn.enabled = bool(design["cdn"])
    cfg.db.workers = int(design["db_workers"])
    cfg.db.shards = int(design["shards"])
    cfg.db.read_replicas = int(design["read_replicas"])
    cfg.queue.enabled = bool(design["queue"])
    cfg.queue.consumers = int(design["consumers"])
    return cfg


def design_cost(ch: Challenge, design: Dict) -> float:
    return monthly_cost(apply_design(ch.base, design))


def enumerate_designs(ch: Challenge) -> List[Dict]:
    keys = list(KNOB_LABELS)
    base = default_design(ch)
    grids = [ch.knobs.get(k, [base[k]]) for k in keys]
    seen, out = set(), []
    for combo in itertools.product(*grids):
        d = dict(zip(keys, combo))
        if not d["queue"]:                       # consumers are irrelevant without a queue
            d["consumers"] = base["consumers"]
        sig = tuple(d[k] for k in keys)
        if sig in seen:
            continue
        seen.add(sig)
        out.append(d)
    out.sort(key=lambda d: design_cost(ch, d))
    return out


# ---------------------------------------------------------------- running checks
def check_config(ch: Challenge, design: Dict, check: Check) -> Config:
    cfg = apply_design(ch.base, design)
    cfg.workload.duration_s = check.duration_s
    cfg.events = [Event(e.kind, e.start_s, e.duration_s, e.magnitude) for e in check.events]
    cfg.seed = check.seed
    cfg.name = f"{ch.title}: {check.name}"
    return cfg


def run_check(ch: Challenge, design: Dict, check: Check, keep_result: bool = False) -> Dict:
    cfg = check_config(ch, design, check)
    res = Simulation(cfg).run()
    tl = timeline(res)
    s = summarize(res, tl)
    lag = s["queue"]["lag_p95_s"] if s["queue"] else None
    reasons = []
    if s["p99_ms"] > check.p99_ms:
        reasons.append(f"p99 {s['p99_ms']:.0f} ms > {check.p99_ms:g} ms")
    if s["success_rate"] < check.min_success:
        reasons.append(f"success {s['success_rate']:.2%} < {check.min_success:.1%}")
    if check.max_lag_s is not None and lag is not None and lag > check.max_lag_s:
        reasons.append(f"write lag {lag:.1f} s > {check.max_lag_s:g} s")
    out = dict(name=check.name, passed=not reasons, reasons=reasons, p99_ms=s["p99_ms"],
               success=s["success_rate"], lag_p95_s=lag, bottleneck=s["bottleneck"],
               peak_util=max((t["peak_util"] for t in s["tiers"].values()), default=0.0))
    if keep_result:
        out["res"], out["tl"], out["summary"] = res, tl, s
    return out


def run_suite(ch: Challenge, design: Dict, stop_on_fail: bool = False, keep_results: bool = False) -> List[Dict]:
    out = []
    for c in ch.checks:
        r = run_check(ch, design, c, keep_result=keep_results)
        out.append(r)
        if stop_on_fail and not r["passed"]:
            break
    return out


# ---------------------------------------------------------------- screening and scoring
def screen(ch: Challenge, design: Dict, steady_limit: float = 0.92) -> bool:
    """Cheap analytic filter used by the optimizer: skip designs whose steady-state napkin math is already hopeless."""
    cfg = apply_design(ch.base, design)
    return all(u <= steady_limit for u in expected_utilization(cfg).values())


def load_optima() -> Dict:
    try:
        with open(OPTIMA_PATH) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def score_design(ch: Challenge, design: Dict, results: List[Dict], optimum_cost: Optional[float]) -> Dict:
    cost = design_cost(ch, design)
    passed = sum(r["passed"] for r in results)
    total = len(results)
    all_pass = passed == total
    over = cost > ch.budget
    reliability = 70.0 * passed / total
    cost_pts = 0.0
    if all_pass and not over and optimum_cost:
        cost_pts = 30.0 * min(1.0, optimum_cost / cost)
    return dict(cost=cost, passed=passed, total=total, all_pass=all_pass, over_budget=over,
                reliability=reliability, cost_pts=cost_pts, total_score=reliability + cost_pts,
                optimum_cost=optimum_cost, efficiency=(optimum_cost / cost) if (optimum_cost and cost) else None)


# ---------------------------------------------------------------- the challenges
def challenges() -> Dict[str, Challenge]:
    out: Dict[str, Challenge] = {}

    # --- A: launch day -------------------------------------------------
    out["launch"] = Challenge(
        id="launch",
        title="Launch day: URL shortener",
        story=("Your link shortener is featured on a front page tomorrow. Normal load is 600 requests per second, "
               "95% of them reads. Design the cheapest system that stays fast through a surprise spike and "
               "through the loss of two app servers."),
        base=Config(
            name="Launch day",
            app=AppTier(replicas=3, workers=8, latency_ms=20),
            cache=CacheTier(hit_rate=0.85),
            db=DBTier(workers=16, read_ms=8, write_ms=25),
            workload=Workload(rps=600, read_ratio=0.95, duration_s=40, timeout_ms=1000),
        ),
        knobs=dict(app_replicas=list(range(2, 9)), app_workers=[4, 8, 16], cache=[True, False],
                   cdn=[False, True], db_workers=[4, 8, 16, 32]),
        checks=[
            Check("Steady traffic", "Normal day: 600 rps.", [], 35, 250, 0.995, seed=1001),
            Check("Front-page spike", "Traffic doubles for 15 seconds.",
                  [Event("traffic_spike", 10, 15, 2.0)], 40, 600, 0.98, seed=1002),
            Check("Lose two servers", "Two app replicas crash for 20 seconds.",
                  [Event("kill_app", 10, 20, 2)], 40, 600, 0.98, seed=1003),
        ],
        budget=600,
        industry="Social",
        hints=["Capacity per replica is workers / latency. Do the napkin math before touching the knobs.",
               "A CDN or cache removes load from tiers further in. What happens to the database if the cache is gone?"],
    )

    # --- B: write storm -------------------------------------------------
    out["writes"] = Challenge(
        id="writes",
        title="Write storm: chat service",
        story=("A chat product sends 700 requests per second, 65% of them writes. Messages may appear a moment late "
               "but must never be lost or slow to send. A marketing push doubles traffic, and the database "
               "sometimes runs slower than normal."),
        base=Config(
            name="Write storm",
            app=AppTier(replicas=3, workers=8, latency_ms=15),
            cache=CacheTier(hit_rate=0.6),
            db=DBTier(workers=16, read_ms=8, write_ms=25),
            workload=Workload(rps=700, read_ratio=0.35, duration_s=40, timeout_ms=1000),
        ),
        knobs=dict(app_replicas=[2, 3, 4, 5, 6], db_workers=[8, 16, 24, 32], shards=[1, 2, 4],
                   read_replicas=[0, 1, 2], queue=[False, True], consumers=[8, 16, 24, 32]),
        checks=[
            Check("Steady traffic", "Normal day: 700 rps, mostly writes.", [], 35, 300, 0.995, max_lag_s=2.0, seed=2001),
            Check("Marketing burst", "Traffic doubles for 15 seconds.",
                  [Event("traffic_spike", 10, 15, 2.0)], 45, 500, 0.99, max_lag_s=10.0, seed=2002),
            Check("Slow database", "Database runs 1.5x slower for 20 seconds.",
                  [Event("db_slow", 10, 20, 1.5)], 40, 800, 0.98, max_lag_s=15.0, seed=2003),
        ],
        budget=900,
        industry="Social",
        hints=["Read replicas serve reads only. Look at the read/write mix before buying them.",
               "A queue protects the client from a slow database, but the database still has to drain it."],
    )

    # --- C: cache failure drill -------------------------------------------
    out["cache"] = Challenge(
        id="cache",
        title="Cache failure drill",
        story=("A product page gets 600 requests per second and 95% are reads. The cache normally hits 90% of the "
               "time, which hides how weak the database is. Your team will unplug the cache during a game day. "
               "Keep the site up, with the cache gone and a server down at the same time."),
        base=Config(
            name="Cache drill",
            app=AppTier(replicas=3, workers=8, latency_ms=20),
            cache=CacheTier(hit_rate=0.9),
            db=DBTier(workers=4, read_ms=12, write_ms=25),
            workload=Workload(rps=600, read_ratio=0.95, duration_s=40, timeout_ms=1000),
        ),
        knobs=dict(app_replicas=[2, 3, 4, 5, 6], db_workers=[4, 8, 16, 32], read_replicas=[0, 1, 2, 3]),
        checks=[
            Check("Steady traffic", "Normal day: the cache is warm.", [], 35, 250, 0.995, seed=3001),
            Check("Cache goes cold", "Hit rate collapses to 20% for 20 seconds, then recovers.",
                  [Event("cold_cache", 10, 20, 0.2)], 45, 800, 0.98, seed=3002),
            Check("Double fault", "Cold cache and one app replica lost at the same time.",
                  [Event("cold_cache", 10, 20, 0.2), Event("kill_app", 10, 20, 1)], 45, 800, 0.97, seed=3003),
        ],
        budget=600,
        industry="E-commerce",
        hints=["Size the database for the miss path, not the happy path: reads x (1 - hit rate) x read time.",
               "Replicas multiply database cost. Compare them with simply buying bigger nodes."],
    )

    # --- D: flash sale ----------------------------------------------------
    out["flash"] = Challenge(
        id="flash", industry="E-commerce",
        title="Flash sale: checkout",
        story=("Half of your 500 requests per second are people browsing and half are placing orders. At noon a "
               "flash sale triples traffic for a few seconds, and the payment database has been flaky lately. "
               "Orders must be accepted fast; slightly late bookkeeping is fine."),
        base=Config(
            name="Flash sale",
            app=AppTier(replicas=3, workers=8, latency_ms=25),
            cache=CacheTier(hit_rate=0.8),
            db=DBTier(workers=16, read_ms=8, write_ms=30),
            workload=Workload(rps=500, read_ratio=0.5, duration_s=40, timeout_ms=1000),
        ),
        knobs=dict(app_replicas=[2, 3, 4, 5, 6, 7, 8], cache=[True, False], cdn=[False, True],
                   db_workers=[8, 16, 24, 32], queue=[False, True], consumers=[8, 16, 24]),
        checks=[
            Check("Steady traffic", "A normal afternoon: 500 rps.", [], 35, 250, 0.995, max_lag_s=2.0, seed=4001),
            Check("Flash-sale rush", "Traffic triples for 12 seconds.",
                  [Event("traffic_spike", 10, 12, 3.0)], 40, 700, 0.97, max_lag_s=12.0, seed=4002),
            Check("Flaky payment database", "The database runs 1.5x slower for 20 seconds.",
                  [Event("db_slow", 10, 20, 1.5)], 40, 800, 0.98, max_lag_s=15.0, seed=4003),
        ],
        budget=850,
        hints=["Triple the traffic, triple the napkin math: how many workers does the app tier need at the peak?",
               "A queue protects order intake, but the database still has to catch up afterwards."],
    )

    # --- E: payments ledger -----------------------------------------------
    out["ledger"] = Challenge(
        id="ledger", industry="Fintech",
        title="Payments ledger: the hot account",
        story=("A payments ledger handles 400 requests per second, 60% of them writes, and every write must be "
               "stored before it is acknowledged (no async queue). Half of all writes hit one very busy merchant "
               "account. Month-end traffic is 2.5x normal, and the primary can run slow."),
        base=Config(
            name="Payments ledger",
            app=AppTier(replicas=3, workers=8, latency_ms=15),
            cache=CacheTier(hit_rate=0.7),
            db=DBTier(workers=8, read_ms=8, write_ms=30, shards=1, hot_share=0.5),
            workload=Workload(rps=400, read_ratio=0.4, duration_s=40, timeout_ms=1000),
        ),
        knobs=dict(app_replicas=[2, 3, 4, 5], db_workers=[8, 16, 24, 32, 48], shards=[1, 2, 4],
                   read_replicas=[0, 1, 2]),
        checks=[
            Check("Steady traffic", "A normal day: 400 rps.", [], 35, 250, 0.995, seed=5001),
            Check("Month-end burst", "Traffic rises 2.5x for 15 seconds.",
                  [Event("traffic_spike", 10, 15, 2.5)], 40, 700, 0.97, seed=5002),
            Check("Slow primary", "Database runs 2x slower for 15 seconds.",
                  [Event("db_slow", 10, 15, 2.0)], 40, 800, 0.97, seed=5003),
        ],
        budget=900,
        hints=["One merchant sends half the writes to a single shard. Does a third shard help that shard at all?",
               "Read replicas cannot help with writes. Check what mix of load the busiest node really sees."],
    )

    # --- F: game launch -----------------------------------------------------
    out["game"] = Challenge(
        id="game", industry="Gaming",
        title="Game launch: the leaderboard",
        story=("Your game's leaderboard serves 800 requests per second, 90% reads. Launch day brings a surge, a "
               "bad deploy can empty the cache, and servers can drop out. Players quit when it lags: keep it fast."),
        base=Config(
            name="Game launch",
            app=AppTier(replicas=3, workers=8, latency_ms=12),
            cache=CacheTier(hit_rate=0.9),
            db=DBTier(workers=8, read_ms=10, write_ms=25),
            workload=Workload(rps=800, read_ratio=0.9, duration_s=40, timeout_ms=1000),
        ),
        knobs=dict(app_replicas=[2, 3, 4, 5, 6, 7], app_workers=[4, 8, 16], cache=[True, False], cdn=[False, True],
                   db_workers=[8, 16, 32], read_replicas=[0, 1, 2]),
        checks=[
            Check("Steady traffic", "Normal evening: 800 rps.", [], 35, 200, 0.995, seed=6001),
            Check("Launch surge", "Traffic rises 2.5x for 12 seconds.",
                  [Event("traffic_spike", 10, 12, 2.5)], 40, 600, 0.97, seed=6002),
            Check("Bad deploy", "Cache hit rate collapses to 30% and two servers are lost.",
                  [Event("cold_cache", 10, 18, 0.3), Event("kill_app", 10, 18, 2)], 45, 800, 0.95, seed=6003),
        ],
        budget=700,
        hints=["A CDN removes reads before they reach any of your servers. What does it do to the other tiers' napkin math?",
               "When the cache is cold, the database sees every read. Do you have the capacity for that?"],
    )

    order = ["launch", "cache", "writes", "flash", "ledger", "game"]
    return {k: out[k] for k in order}
