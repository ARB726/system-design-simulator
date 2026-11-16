"""Compare timeline analysis against a Git revision on identical retained traces."""
import argparse
import gc
import json
import platform
from pathlib import Path
import statistics
import subprocess
import sys
from time import perf_counter
import tracemalloc
import types

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
from sim.analysis import timeline
from sim.config import Config, Workload
from sim.execution import analyzed_run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-ref", default="origin/main")
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--output", type=Path, default=Path(".local/analysis-benchmark.json"))
    args = parser.parse_args()
    if args.rounds < 1:
        parser.error("rounds must be positive")
    revision = subprocess.check_output(["git", "rev-parse", args.baseline_ref], text=True).strip()
    source = subprocess.check_output(["git", "show", f"{revision}:sim/analysis.py"], text=True)
    baseline = types.ModuleType("sim._baseline_analysis")
    exec(compile(source, "baseline_analysis.py", "exec"), baseline.__dict__)
    cases = []
    report = dict(baseline=revision, python=sys.version, platform=platform.platform(), pandas=pd.__version__, cases=cases)
    for rate in (500, 2000):
        cfg = Config(workload=Workload(rps=rate, duration_s=20, warmup_s=2))
        res, _, _, _ = analyzed_run(cfg)
        funcs = {"baseline": baseline.timeline, "candidate": timeline}
        pd.testing.assert_frame_equal(baseline.timeline(res), timeline(res), check_exact=True)
        timings = {name: [] for name in funcs}
        for round_index in range(args.rounds):
            for name in (list(funcs) if round_index % 2 == 0 else list(reversed(funcs))):
                started = perf_counter()
                funcs[name](res)
                timings[name].append(perf_counter() - started)
        peaks = {}
        for name, func in funcs.items():
            gc.collect()
            tracemalloc.start()
            func(res)
            peaks[name] = tracemalloc.get_traced_memory()[1]
            tracemalloc.stop()
        case = dict(config=cfg.to_dict(), requests=len(res.requests), samples_s=timings,
                    median_s={k: statistics.median(v) for k, v in timings.items()},
                    peak_traced_bytes=peaks, pipeline_timings=res.timings, exact_match=True)
        cases.append(case)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
