"""Profile summary-engine workloads without including imports or analysis charts."""
import argparse
import cProfile
import importlib.metadata
import json
from pathlib import Path
import platform
import pstats
import sys
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sim.config import Config, Workload
from sim.engine import run_summary


def cases():
    baseline = Config(workload=Workload(rps=500, duration_s=20, warmup_s=2), seed=7)
    overload = Config(workload=Workload(rps=1500, duration_s=20, warmup_s=2, timeout_ms=100), seed=7)
    overload.app.replicas, overload.app.workers = 1, 2
    retries = Config(workload=Workload(rps=1000, duration_s=20, warmup_s=2, timeout_ms=100), seed=7)
    retries.app.replicas, retries.app.workers = 1, 2
    retries.policy.max_retries = 3
    queued = Config(workload=Workload(rps=700, duration_s=20, warmup_s=2, read_ratio=.2), seed=7)
    queued.queue.enabled = True
    return dict(baseline=baseline, overload=overload, retries=retries, queued_writes=queued)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(".local/engine-profile.json"))
    args = parser.parse_args()
    reports = {}
    for name, cfg in cases().items():
        run_summary(cfg)  # Warm initialization outside measurement.
        started = perf_counter()
        expected = run_summary(cfg)
        elapsed = perf_counter() - started
        profile = cProfile.Profile()
        actual = profile.runcall(run_summary, cfg)
        assert actual == expected, f"Profile changed results: {name}"
        stats = pstats.Stats(profile)
        functions = []
        for (filename, line, function), (primitive, calls, own, cumulative, _) in getattr(stats, "stats").items():
            functions.append(dict(file=Path(filename).name, line=line, function=function,
                                  primitive_calls=primitive, calls=calls, own_s=own, cumulative_s=cumulative))
        reports[name] = dict(config=cfg.to_dict(), unprofiled_s=elapsed, metrics=actual,
                             arrival_limit_calls=sum(row["calls"] for row in functions
                                                     if row["file"] == "limits.py" and row["function"] == "arrival_limit"),
                             top_own=sorted(functions, key=lambda row: row["own_s"], reverse=True)[:25],
                             top_cumulative=sorted(functions, key=lambda row: row["cumulative_s"], reverse=True)[:25])
        print(f"{name}: {elapsed:.3f}s unprofiled", flush=True)
    report = dict(python=sys.version, platform=platform.platform(),
                  packages={name: importlib.metadata.version(name) for name in ("simpy", "numpy", "pandas")},
                  note="One seed per workload. cProfile adds overhead; overlapping cumulative times cannot be summed.",
                  cases=reports)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
