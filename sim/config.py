"""Design spec for the simulator: plain dataclasses, easy to serialize.

Everything the engine needs to know about a design lives in `Config`.
Presets at the bottom are small, self-contained "labs" with a story.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional

LB_STRATEGIES: Dict[str, str] = {
    "least_queue": "Least queue (smart LB)",
    "round_robin": "Round robin",
    "random": "Random",
    "shared": "Shared queue (ideal M/M/c)",
}

# kind -> (label, magnitude meaning, default magnitude)
EVENT_KINDS: Dict[str, tuple] = {
    "traffic_spike": ("Traffic spike", "x normal traffic", 2.0),
    "kill_app": ("App replicas crash", "replicas lost", 1.0),
    "cold_cache": ("Cache goes cold", "hit rate during event", 0.0),
    "db_slow": ("Database slows down", "x latency", 4.0),
}

COLD_CACHE_WARMUP_S = 15.0  # hit rate climbs back linearly after a cold-cache event


@dataclass
class AppTier:
    replicas: int = 3
    workers: int = 8              # concurrent requests one replica can serve
    latency_ms: float = 20.0      # mean service time per request
    lb_strategy: str = "least_queue"
    max_queue: Optional[int] = 200  # per replica; extra requests are dropped (503)


@dataclass
class CacheTier:
    enabled: bool = True
    hit_rate: float = 0.85
    latency_ms: float = 1.0
    workers: int = 64


@dataclass
class DBTier:
    workers: int = 16             # connections per node
    read_ms: float = 8.0
    write_ms: float = 25.0
    read_replicas: int = 0        # 0 = primary serves reads too
    max_queue: Optional[int] = 500


@dataclass
class Workload:
    rps: float = 900.0
    read_ratio: float = 0.95
    duration_s: float = 60.0
    timeout_ms: Optional[float] = 1000.0  # client gives up after this long
    warmup_s: float = 5.0                 # excluded from summary statistics


@dataclass
class Event:
    kind: str
    start_s: float
    duration_s: float
    magnitude: float

    @property
    def end_s(self) -> float:
        return self.start_s + self.duration_s

    def label(self) -> str:
        name = EVENT_KINDS[self.kind][0]
        m = self.magnitude
        if self.kind == "traffic_spike":
            return f"{name} x{m:g}"
        if self.kind == "kill_app":
            return f"{name} (-{int(m)})"
        if self.kind == "cold_cache":
            return f"{name} ({m:.0%} hits)"
        return f"{name} x{m:g}"


@dataclass
class Config:
    name: str = "Custom design"
    app: AppTier = field(default_factory=AppTier)
    cache: CacheTier = field(default_factory=CacheTier)
    db: DBTier = field(default_factory=DBTier)
    workload: Workload = field(default_factory=Workload)
    events: List[Event] = field(default_factory=list)
    seed: int = 42
    app_only: bool = False  # used by the M/M/c validation: just the app tier

    def to_dict(self) -> dict:
        return asdict(self)


def config_from_dict(d: dict) -> Config:
    return Config(
        name=d.get("name", "Custom design"),
        app=AppTier(**d["app"]),
        cache=CacheTier(**d["cache"]),
        db=DBTier(**d["db"]),
        workload=Workload(**d["workload"]),
        events=[Event(**e) for e in d.get("events", [])],
        seed=d.get("seed", 42),
        app_only=d.get("app_only", False),
    )


# ---------------------------------------------------------------- back of envelope
def app_capacity_rps(cfg: Config) -> float:
    a = cfg.app
    return a.replicas * a.workers * 1000.0 / a.latency_ms


def expected_utilization(cfg: Config) -> Dict[str, float]:
    """The napkin math an interviewer wants to see: steady-state utilization per tier."""
    w, a, c, d = cfg.workload, cfg.app, cfg.cache, cfg.db
    reads = w.rps * w.read_ratio
    writes = w.rps - reads
    miss = (1.0 - c.hit_rate) if c.enabled else 1.0
    db_reads = reads * miss
    out = {"app": w.rps * a.latency_ms / 1000.0 / (a.replicas * a.workers)}
    if cfg.app_only:
        return out
    if c.enabled:
        out["cache"] = reads * c.latency_ms / 1000.0 / c.workers
    if d.read_replicas > 0:
        out["db_primary"] = writes * d.write_ms / 1000.0 / d.workers
        out["db_replicas"] = db_reads * d.read_ms / 1000.0 / (d.read_replicas * d.workers)
    else:
        out["db_primary"] = (writes * d.write_ms + db_reads * d.read_ms) / 1000.0 / d.workers
    return out


def replicas_needed(rps: float, latency_ms: float, workers: int, target_util: float = 0.7) -> int:
    return max(1, math.ceil(rps * latency_ms / 1000.0 / (workers * target_util)))


# ---------------------------------------------------------------- presets
@dataclass
class Preset:
    cfg: Config
    story: str
    try_this: str


def presets() -> Dict[str, Preset]:
    out: Dict[str, Preset] = {}

    out["Read-heavy: URL shortener"] = Preset(
        Config(
            name="URL shortener",
            app=AppTier(replicas=3, workers=8, latency_ms=20),
            cache=CacheTier(hit_rate=0.85),
            db=DBTier(workers=16, read_ms=8, write_ms=25),
            workload=Workload(rps=900, read_ratio=0.95, duration_s=60),
            events=[Event("traffic_spike", 25, 15, 2.0)],
        ),
        "A read-heavy service with a cache in front of the database. It is comfortable at "
        "normal load, then a viral link doubles traffic for 15 seconds.",
        "Which tier saturates first? Then raise app replicas and re-run. How many do you "
        "need so the spike stays under 80% utilization?",
    )

    out["Write-heavy: chat messages"] = Preset(
        Config(
            name="Chat messages",
            app=AppTier(replicas=4, workers=8, latency_ms=15),
            cache=CacheTier(hit_rate=0.6),
            db=DBTier(workers=12, read_ms=8, write_ms=25),
            workload=Workload(rps=600, read_ratio=0.5, duration_s=60),
            events=[Event("traffic_spike", 25, 20, 1.5)],
        ),
        "Half the traffic is writes, and every write must hit the single database primary.",
        "Add read replicas and re-run: reads move away but the primary stays hot. Why? "
        "What would you change in the write path instead (batching, async queue, sharding)?",
    )

    out["Failure: cache goes cold"] = Preset(
        Config(
            name="Cache cold start",
            app=AppTier(replicas=4, workers=8, latency_ms=15),
            cache=CacheTier(hit_rate=0.95),
            db=DBTier(workers=8, read_ms=8, write_ms=25),
            workload=Workload(rps=1200, read_ratio=0.95, duration_s=70),
            events=[Event("cold_cache", 25, 10, 0.0)],
        ),
        "A 95% hit rate hides how little the database is doing. When the cache restarts, "
        "the full read load lands on a database sized for 5% of it.",
        "Compare database utilization before and during the event. Try read replicas, then "
        "think about request coalescing and cache warm-up.",
    )

    out["Failure: lose app replicas"] = Preset(
        Config(
            name="Replica failure",
            app=AppTier(replicas=4, workers=8, latency_ms=20),
            cache=CacheTier(hit_rate=0.85),
            db=DBTier(workers=16, read_ms=8, write_ms=25),
            workload=Workload(rps=1000, read_ratio=0.95, duration_s=70),
            events=[Event("kill_app", 25, 20, 2.0)],
        ),
        "Four replicas look fine at 62% utilization. Then two of them crash.",
        "Find the smallest replica count that survives losing two and stays below ~80%. "
        "This is the N+k redundancy argument interviewers like to hear.",
    )

    out["Lab: load balancing strategy"] = Preset(
        Config(
            name="LB strategy lab",
            app=AppTier(replicas=4, workers=4, latency_ms=20, lb_strategy="random"),
            cache=CacheTier(hit_rate=0.85),
            db=DBTier(workers=16, read_ms=8, write_ms=25),
            workload=Workload(rps=660, read_ratio=0.95, duration_s=60),
            events=[],
        ),
        "Same hardware, same load (about 83% utilization), but requests are routed randomly, "
        "so some replicas queue while others sit idle.",
        "Switch the strategy to least-queue and then to a shared queue. Watch p95 latency "
        "fall even though capacity never changed.",
    )

    out["Blank canvas"] = Preset(
        Config(name="My design"),
        "Start from sensible defaults and build your own design.",
        "Use the napkin-math table first: predict each tier's utilization, then run the "
        "simulation and see where you were wrong.",
    )
    return out
