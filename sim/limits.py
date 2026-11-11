"""Server-side workload limits, independent of browser widget constraints."""
import math
import os


class SimulationLimitError(ValueError):
    pass


def arrival_limit():
    return int(os.environ.get("SYSDESIGN_MAX_ARRIVALS", "2000000"))


def validate_config(cfg):
    def number(name, value, low, high):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
            raise SimulationLimitError(f"{name} must be finite and between {low} and {high}.")

    def integer(name, value, low, high):
        number(name, value, low, high)
        if not isinstance(value, int):
            raise SimulationLimitError(f"{name} must be an integer.")

    w, a, d = cfg.workload, cfg.app, cfg.db
    number("Request rate", w.rps, 0.01, 100000)
    number("Duration", w.duration_s, 0.1, 600)
    number("Warmup", w.warmup_s, 0, w.duration_s - 0.000001)
    number("Read ratio", w.read_ratio, 0, 1)
    if w.timeout_ms is not None:
        number("Timeout", w.timeout_ms, 1, 60000)
    integer("Seed", cfg.seed, 0, 2**63 - 1)
    integer("App replicas", a.replicas, 1, 64)
    integer("App workers", a.workers, 1, 256)
    integer("Database shards", d.shards, 1, 64)
    integer("Read replicas", d.read_replicas, 0, 16)
    integer("Database workers", d.workers, 1, 256)
    integer("Cache workers", cfg.cache.workers, 1, 1024)
    integer("Queue consumers", cfg.queue.consumers, 1, 256)
    integer("Queue depth", cfg.queue.max_depth, 1, 100000)
    for name, value in (("App queue", a.max_queue), ("Database queue", d.max_queue)):
        if value is not None:
            integer(name, value, 1, 100000)
    for value in (a.latency_ms, cfg.cache.latency_ms, cfg.cdn.latency_ms,
                  cfg.queue.enqueue_ms, d.read_ms, d.write_ms):
        number("Service time", value, 0.001, 60000)
    for value in (cfg.cache.hit_rate, cfg.cdn.hit_rate, d.hot_share):
        number("Hit rate / hot-key share", value, 0, 1)
    from .config import LB_STRATEGIES, EVENT_KINDS
    if a.lb_strategy not in LB_STRATEGIES:
        raise SimulationLimitError("Unknown load-balancing strategy.")
    if len(cfg.events) > 8:
        raise SimulationLimitError("At most eight chaos events are allowed.")
    spike_factor = 1.0
    for event in cfg.events:
        if event.kind not in EVENT_KINDS:
            raise SimulationLimitError("Unknown chaos event.")
        number("Event start", event.start_s, 0, 600)
        number("Event duration", event.duration_s, 0.001, 600)
        number("Event magnitude", event.magnitude, 0, 100)
        if event.kind == "cold_cache":
            number("Cold-cache hit rate", event.magnitude, 0, 1)
        if event.kind == "db_slow":
            number("Database slowdown", event.magnitude, 0.001, 100)
        if event.kind == "kill_app":
            number("Replicas lost", event.magnitude, 0, 64)
            if int(event.magnitude) != event.magnitude:
                raise SimulationLimitError("Replicas lost must be an integer.")
        if event.kind == "traffic_spike":
            spike_factor *= max(1, event.magnitude)
    if w.rps * w.duration_s * spike_factor > arrival_limit() * 0.9:
        raise SimulationLimitError("This run exceeds the server's arrival budget. Reduce traffic, duration, or spike magnitude.")
