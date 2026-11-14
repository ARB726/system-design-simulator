"""Measure serial versus bounded parallel load sweeps, including startup cost."""
import argparse
import json
import os
from pathlib import Path
import platform
import statistics
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sim.batch import worker_limit
from sim.config import Config
from sim.experiments import sweep_load


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--output", type=Path, default=Path(".local/sweep-benchmark.json"))
    args = parser.parse_args()
    if not 2 <= args.workers <= worker_limit() or args.rounds < 3:
        parser.error(f"Use 2 to {worker_limit()} workers and at least three rounds.")
    cfg, values = Config(seed=7), [400, 600, 800, 1000, 1200, 1400]
    expected = sweep_load(cfg, values, duration_s=25, warmup_s=5)
    assert sweep_load(cfg, values, duration_s=25, warmup_s=5, workers=args.workers).equals(expected)
    samples = {"serial": [], "parallel": []}
    for index in range(args.rounds):
        order = list(samples) if index % 2 == 0 else list(reversed(samples))
        for mode in order:
            start = time.perf_counter()
            result = sweep_load(cfg, values, duration_s=25, warmup_s=5, workers=1 if mode == "serial" else args.workers)
            elapsed = time.perf_counter() - start
            assert result.equals(expected), "Point metrics changed"
            samples[mode].append(elapsed)
    medians = {mode: statistics.median(times) for mode, times in samples.items()}
    report = dict(python=sys.version, platform=platform.platform(), cpu=platform.processor(),
                  logical_cpus=os.cpu_count(), config=cfg.to_dict(), target_rps=values, duration_s=25, warmup_s=5,
                  workers=args.workers, rounds=args.rounds, samples_s=samples, median_s=medians,
                  ratio=medians["serial"] / medians["parallel"], metrics_equal=True,
                  note="Includes interpreter/import startup. Local wall-clock observations, not a production capacity claim.")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(dict(median_s=medians, ratio=report["ratio"], metrics_equal=True)), flush=True)


if __name__ == "__main__":
    main()
