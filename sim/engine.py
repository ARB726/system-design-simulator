"""Discrete-event simulation of: clients -> load balancer -> app replicas -> cache -> database.

Modelling choices (stated so they can be defended in an interview):
  * Arrivals are Poisson; service times are exponential. That makes a single tier an
    M/M/c queue, which `tests/test_engine.py` checks against the Erlang C formulas.
  * Tiers are queues in tandem: a worker is released before the next tier is called.
  * A client abandons a request after `timeout_ms`; a bounded queue drops the overflow.
  * Failures are counted at the timeout value when computing latency percentiles, so an
    overloaded system cannot look healthy by only reporting its lucky survivors.
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Callable, List, Optional

import pandas as pd
import simpy

from .config import COLD_CACHE_WARMUP_S, Config

SAMPLE_DT = 0.25  # seconds between utilization / queue samples


class Events:
    """Time-varying conditions derived from the chaos events (stateless functions of t)."""

    def __init__(self, cfg: Config):
        by = lambda k: [e for e in cfg.events if e.kind == k]
        self.spikes = by("traffic_spike")
        self.kills = by("kill_app")
        self.cold = by("cold_cache")
        self.slow = by("db_slow")
        self.base_hit = cfg.cache.hit_rate

    @staticmethod
    def _active(evts, t):
        return [e for e in evts if e.start_s <= t < e.end_s]

    def arrival_factor(self, t: float) -> float:
        f = 1.0
        for e in self._active(self.spikes, t):
            f *= e.magnitude
        return f

    def max_arrival_factor(self) -> float:
        f = 1.0
        for e in self.spikes:
            f *= max(1.0, e.magnitude)
        return f

    def killed(self, t: float) -> int:
        return sum(int(e.magnitude) for e in self._active(self.kills, t))

    def db_factor(self, t: float) -> float:
        f = 1.0
        for e in self._active(self.slow, t):
            f *= e.magnitude
        return f

    def hit_rate(self, t: float) -> float:
        h = self.base_hit
        for e in self.cold:
            if e.start_s <= t < e.end_s:
                h = min(h, e.magnitude)
            elif e.end_s <= t < e.end_s + COLD_CACHE_WARMUP_S:
                frac = (t - e.end_s) / COLD_CACHE_WARMUP_S
                h = min(h, e.magnitude + (self.base_hit - e.magnitude) * frac)
        return h


class Tier:
    """A group of nodes; each node is a pool of workers with its own FIFO queue."""

    def __init__(self, env: simpy.Environment, n_nodes: int, workers: int, max_queue: Optional[int]):
        self.nodes = [simpy.Resource(env, capacity=workers) for _ in range(n_nodes)]
        self.workers = workers
        self.max_queue = max_queue
        self._rr = 0

    def load(self, i: int) -> int:
        r = self.nodes[i]
        return len(r.queue) + r.count

    def pick(self, lo: int, hi: int, strategy: str, rng: random.Random) -> Optional[int]:
        """Choose a node index in [lo, hi)."""
        n = hi - lo
        if n <= 0:
            return None
        if n == 1 or strategy == "shared":
            return lo
        if strategy == "random":
            return lo + rng.randrange(n)
        if strategy == "round_robin":
            self._rr += 1
            return lo + self._rr % n
        loads = [self.load(i) for i in range(lo, hi)]  # least_queue
        best = min(loads)
        ties = [lo + i for i, v in enumerate(loads) if v == best]
        return ties[0] if len(ties) == 1 else rng.choice(ties)


@dataclass
class SimResult:
    cfg: Config
    requests: pd.DataFrame   # one row per request
    series: pd.DataFrame     # sampled utilization / queue depth
    warnings: List[str]
    runtime_s: float


class Simulation:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.env = simpy.Environment()
        self.rng = random.Random(cfg.seed)
        self.ev = Events(cfg)
        self.warnings: List[str] = []
        a, c, d, w = cfg.app, cfg.cache, cfg.db, cfg.workload

        if a.lb_strategy == "shared":
            mq = a.max_queue * a.replicas if a.max_queue else None
            self.app = Tier(self.env, 1, a.replicas * a.workers, mq)
            if cfg.events and any(e.kind == "kill_app" for e in cfg.events):
                self.warnings.append("Replica crashes are ignored with the shared-queue strategy.")
        else:
            self.app = Tier(self.env, a.replicas, a.workers, a.max_queue)
        self.cache = Tier(self.env, 1, c.workers, None) if (c.enabled and not cfg.app_only) else None
        self.db = None if cfg.app_only else Tier(self.env, 1 + d.read_replicas, d.workers, d.max_queue)

        self.timeout_s = w.timeout_ms / 1000.0 if w.timeout_ms else None
        self.records: list = []
        self.samples: list = []
        self.inflight: dict = {}
        self._next_id = 0

    # ---------------------------------------------------------------- helpers
    def _app_alive(self, t: float) -> int:
        if self.cfg.app.lb_strategy == "shared":
            return 1
        return max(0, self.cfg.app.replicas - self.ev.killed(t))

    def _app_node_alive(self, i: int) -> bool:
        return self.cfg.app.lb_strategy == "shared" or i < self._app_alive(self.env.now)

    def _serve(self, tier: Tier, idx: int, mean_s: float, deadline: Optional[float],
               alive: Optional[Callable[[int], bool]] = None):
        """Queue for a worker on one node, hold it for a service time. Returns a status string."""
        env, res = self.env, tier.nodes[idx]
        if tier.max_queue is not None and len(res.queue) >= tier.max_queue:
            return "dropped"
        with res.request() as req:
            if deadline is None:
                yield req
            else:
                got = yield req | env.timeout(max(deadline - env.now, 0.0))
                if req not in got:
                    return "timeout"          # client gave up while queued
            if alive is not None and not alive(idx):
                return "error"                # the replica died under us
            yield env.timeout(self.rng.expovariate(1.0 / mean_s))
        return "ok"

    # ---------------------------------------------------------------- one request
    def _request(self):
        env, cfg, rng = self.env, self.cfg, self.rng
        a, c, d = cfg.app, cfg.cache, cfg.db
        rid = self._next_id
        self._next_id += 1
        t0 = env.now
        is_read = rng.random() < cfg.workload.read_ratio
        self.inflight[rid] = (t0, is_read)
        deadline = t0 + self.timeout_s if self.timeout_s else None
        hit = None

        idx = self.app.pick(0, self._app_alive(t0), a.lb_strategy, rng)
        if idx is None:
            status = "error"                  # every replica is down
        else:
            status = yield from self._serve(self.app, idx, a.latency_ms / 1000.0, deadline,
                                            self._app_node_alive)

        if status == "ok" and not cfg.app_only:
            if is_read:
                hit = False
                if self.cache is not None:
                    status = yield from self._serve(self.cache, 0, c.latency_ms / 1000.0, deadline)
                    if status == "ok":
                        hit = rng.random() < self.ev.hit_rate(env.now)
                if status == "ok" and not hit:
                    if d.read_replicas > 0:
                        j = self.db.pick(1, 1 + d.read_replicas, "least_queue", rng)
                    else:
                        j = 0
                    mean = d.read_ms / 1000.0 * self.ev.db_factor(env.now)
                    status = yield from self._serve(self.db, j, mean, deadline)
            else:
                mean = d.write_ms / 1000.0 * self.ev.db_factor(env.now)
                status = yield from self._serve(self.db, 0, mean, deadline)

        latency = env.now - t0
        if status == "ok" and deadline is not None and env.now > deadline:
            status = "timeout"                # answered, but too late to matter
        del self.inflight[rid]
        self.records.append((t0, latency, status, is_read, hit))

    # ---------------------------------------------------------------- processes
    def _arrivals(self):
        env, w = self.env, self.cfg.workload
        lam_max = w.rps * self.ev.max_arrival_factor()
        while True:                           # thinning handles the time-varying rate
            yield env.timeout(self.rng.expovariate(lam_max))
            if env.now >= w.duration_s:
                return
            if self.rng.random() * lam_max <= w.rps * self.ev.arrival_factor(env.now):
                env.process(self._request())

    def _sampler(self):
        env, cfg = self.env, self.cfg
        a, d = cfg.app, cfg.db
        while True:
            yield env.timeout(SAMPLE_DT)
            t = env.now
            n_alive = self._app_alive(t)
            nodes = self.app.nodes[:n_alive]
            cap = max(n_alive, 1) * self.app.workers
            row = {
                "t": t,
                "alive_replicas": a.replicas if a.lb_strategy == "shared" else n_alive,
                "util_app": min(1.0, sum(n.count for n in nodes) / cap),
                "q_app": sum(len(n.queue) for n in nodes),
            }
            if self.cache is not None:
                cn = self.cache.nodes[0]
                row["util_cache"] = cn.count / self.cache.workers
                row["q_cache"] = len(cn.queue)
            if self.db is not None:
                p = self.db.nodes[0]
                row["util_db_primary"] = p.count / self.db.workers
                row["q_db_primary"] = len(p.queue)
                if d.read_replicas > 0:
                    reps = self.db.nodes[1:]
                    row["util_db_replicas"] = sum(n.count for n in reps) / (len(reps) * self.db.workers)
                    row["q_db_replicas"] = sum(len(n.queue) for n in reps)
            self.samples.append(row)

    def run(self) -> SimResult:
        t_start = time.perf_counter()
        w = self.cfg.workload
        self.env.process(self._arrivals())
        self.env.process(self._sampler())
        tail = (self.timeout_s + 1.0) if self.timeout_s else 0.0
        self.env.run(until=w.duration_s + tail)
        now = self.env.now
        for t0, is_read in self.inflight.values():   # unfinished work, latency is a lower bound
            self.records.append((t0, now - t0, "incomplete", is_read, None))

        req = pd.DataFrame(self.records, columns=["t", "latency_s", "status", "is_read", "hit"])
        req["latency_ms"] = req.latency_s * 1000.0
        fail_ms = w.timeout_ms if w.timeout_ms else (req.latency_ms.max() if len(req) else 0.0)
        req["eff_ms"] = req.latency_ms.where(req.status.isin(["ok", "incomplete"]), fail_ms)
        req = req.drop(columns="latency_s").sort_values("t").reset_index(drop=True)
        ser = pd.DataFrame(self.samples)
        return SimResult(self.cfg, req, ser, self.warnings, time.perf_counter() - t_start)


def run(cfg: Config) -> SimResult:
    return Simulation(cfg).run()
