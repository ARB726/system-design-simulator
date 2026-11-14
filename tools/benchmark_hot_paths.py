"""Compare current summary execution against a recorded Git revision.

Run from the repository root. Imports and correctness checks are outside timing;
both paths are warmed and measurement order alternates to reduce order bias.
"""
from __future__ import annotations

import argparse
import importlib.metadata
import json
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import time
import types

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sim.config import AppTier, Config, Event, Workload
from sim.engine import run_summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-ref", default="origin/main")
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--output", type=Path, default=Path(".local/hot-path-benchmark.json"))
    args = parser.parse_args()
    if args.rounds < 3:
        parser.error("Use at least three timing rounds.")
    root = Path(__file__).resolve().parents[1]
    revision = subprocess.check_output(["git", "rev-parse", args.baseline_ref], cwd=root, text=True).strip()
    source = subprocess.check_output(["git", "show", f"{revision}:sim/engine.py"], cwd=root, text=True)
    baseline = types.ModuleType("sim._benchmark_baseline")
    sys.modules[baseline.__name__] = baseline
    exec(compile(source, f"{revision}:sim/engine.py", "exec"), baseline.__dict__)
    cases = {
        "default": Config(workload=Workload(rps=500, duration_s=20, warmup_s=1), seed=7),
        "many_replicas": Config(app=AppTier(replicas=32),
                                workload=Workload(rps=1000, duration_s=20, warmup_s=1), seed=7),
        "overlapping_events": Config(workload=Workload(rps=500, duration_s=20, warmup_s=1), seed=7,
                                     events=[Event("traffic_spike", 5, 8, 2), Event("traffic_spike", 8, 5, 2),
                                             Event("kill_app", 8, 3, 1), Event("db_slow", 8, 5, 2)]),
    }
    results = {}
    for name, cfg in cases.items():
        paths = {"baseline": baseline.run_summary, "candidate": run_summary}
        expected = baseline.run_summary(cfg)
        assert run_summary(cfg) == expected, f"Metric mismatch: {name}"
        samples = {mode: [] for mode in paths}
        for round_index in range(args.rounds):
            order = list(paths) if round_index % 2 == 0 else list(reversed(paths))
            for mode in order:
                start = time.perf_counter()
                actual = paths[mode](cfg)
                elapsed = time.perf_counter() - start
                assert actual == expected, f"Metric mismatch: {name}/{mode}"
                samples[mode].append(elapsed)
        medians = {mode: statistics.median(values) for mode, values in samples.items()}
        results[name] = dict(config=cfg.to_dict(), samples_s=samples, median_s=medians,
                             speedup=medians["baseline"] / medians["candidate"], metrics_equal=True)
        print(f"{name}: baseline={medians['baseline']:.4f}s candidate={medians['candidate']:.4f}s "
              f"ratio={results[name]['speedup']:.3f}x", flush=True)
    report = dict(baseline_revision=revision, python=sys.version, platform=platform.platform(),
                  packages={name: importlib.metadata.version(name) for name in ("simpy", "numpy", "pandas")},
                  rounds=args.rounds, results=results)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
