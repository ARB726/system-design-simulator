"""Compare static chunks with dynamic subprocess scheduling, including startup."""
import argparse
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
from time import perf_counter
import types

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sim.batch import summaries, worker_limit
from sim.config import Config, Workload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-ref", default="87157cb")
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--output", type=Path, default=Path(".local/scheduling-benchmark.json"))
    args = parser.parse_args()
    if args.rounds < 3 or worker_limit() < 2:
        parser.error("Use at least three rounds and allow two workers.")
    revision = subprocess.check_output(["git", "rev-parse", args.baseline_ref], text=True).strip()
    source = subprocess.check_output(["git", "show", f"{revision}:sim/batch.py"], text=True)
    baseline = types.ModuleType("sim._baseline_batch")
    baseline.__file__ = str(Path(__file__).resolve().parents[1] / "sim" / "batch.py")
    exec(compile(source, "baseline_batch.py", "exec"), baseline.__dict__)
    reports = {}
    for name, rates in {"balanced": [500] * 6, "uneven": [1500, 50, 1500, 50, 1500, 50]}.items():
        configs = [Config(workload=Workload(rps=rate, duration_s=10, warmup_s=1), seed=7) for rate in rates]
        paths = {"static": baseline.summaries, "dynamic": summaries}
        expected = summaries(configs)
        for func in paths.values():
            assert func(configs, workers=2) == expected
        samples = {mode: [] for mode in paths}
        for round_index in range(args.rounds):
            for mode in (list(paths) if round_index % 2 == 0 else list(reversed(paths))):
                started = perf_counter()
                actual = paths[mode](configs, workers=2)
                elapsed = perf_counter() - started
                assert actual == expected, f"Point results changed: {name}/{mode}"
                samples[mode].append(elapsed)
        medians = {mode: statistics.median(values) for mode, values in samples.items()}
        reports[name] = dict(configs=[cfg.to_dict() for cfg in configs], samples_s=samples, median_s=medians,
                             ratio=medians["static"] / medians["dynamic"], exact_match=True)
        print(f"{name}: {medians}, ratio={reports[name]['ratio']:.3f}x", flush=True)
    report = dict(baseline_revision=revision, python=sys.version, platform=platform.platform(),
                  logical_cpus=os.cpu_count(), workers=2, rounds=args.rounds, cases=reports,
                  note="Both schedulers use the current engine/worker. Includes child startup and JSON IPC; isolates scheduling, not engine changes.")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
