"""Compare full-trace sweep statistics with exact compact execution in fresh processes."""
import argparse
import cProfile
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import platform
import pstats
import statistics
import subprocess
import sys
import time
import tracemalloc

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sim.config import Config, Workload
from sim.engine import run, run_summary
from sim.experiments import _quick


def measure(mode, rps, duration, seed, instrument):
    cfg = Config(workload=Workload(rps=rps, duration_s=duration, warmup_s=1), seed=seed)
    operation = (lambda: _quick(run(cfg))) if mode == "full" else (lambda: run_summary(cfg))
    # Exclude one-time library initialization; measured jobs still use fresh simulations.
    warmup = Config(workload=Workload(rps=1, duration_s=2, warmup_s=1))
    _quick(run(warmup))
    run_summary(warmup)
    if instrument == "memory":
        tracemalloc.start()
    profile = cProfile.Profile() if instrument == "profile" else None
    if profile:
        profile.enable()
    start = time.perf_counter()
    summary = operation()
    seconds = time.perf_counter() - start
    if profile:
        profile.disable()
    peak = tracemalloc.get_traced_memory()[1] if instrument == "memory" else None
    if instrument == "memory":
        tracemalloc.stop()
    result = dict(seconds=seconds, peak_traced_bytes=peak, summary=summary)
    if profile:
        output = io.StringIO()
        pstats.Stats(profile, stream=output).strip_dirs().sort_stats("cumulative").print_stats(12)
        result["profile"] = output.getvalue()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--rps", type=float, default=500)
    parser.add_argument("--duration", type=float, default=20)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--output", type=Path, default=Path(".local/summary-benchmark.json"))
    parser.add_argument("--child", choices=["full", "summary"], help=argparse.SUPPRESS)
    parser.add_argument("--instrument", choices=["timing", "memory", "profile"], default="timing", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.rounds < 1:
        parser.error("rounds must be positive")
    if args.child:
        print(json.dumps(measure(args.child, args.rps, args.duration, args.seed, args.instrument)))
        return
    results = {mode: dict(timings=[], memory=None, profile=None) for mode in ("full", "summary")}
    def child(mode, instrument):
        command = [sys.executable, str(Path(__file__).resolve()), "--child", mode,
                   "--instrument", instrument, "--rps", str(args.rps), "--duration", str(args.duration),
                   "--seed", str(args.seed)]
        return json.loads(subprocess.check_output(command, text=True, timeout=300))
    for round_index in range(args.rounds):
        # Alternate execution order to reduce systematic warmup/load bias.
        for mode in (("full", "summary") if round_index % 2 == 0 else ("summary", "full")):
            results[mode]["timings"].append(child(mode, "timing"))
    for mode in results:
        results[mode]["memory"] = child(mode, "memory")
        results[mode]["profile"] = child(mode, "profile")["profile"]
        results[mode]["median_seconds"] = statistics.median(r["seconds"] for r in results[mode]["timings"])
    reference = results["full"]["timings"][0]["summary"]
    for mode in results:
        for sample in results[mode]["timings"] + [results[mode]["memory"]]:
            if any(abs(sample["summary"][key] - value) > max(1e-12, abs(value) * 1e-12)
                   for key, value in reference.items()):
                raise RuntimeError("Summary equivalence check failed")
    report = dict(measured_at=datetime.now(timezone.utc).isoformat(),
                  environment=dict(python=sys.version, platform=platform.platform(),
                                  cpu=platform.processor(), logical_cpus=os.cpu_count()),
                  workload=dict(rps=args.rps, duration_s=args.duration, warmup_s=1, seed=args.seed,
                                rounds=args.rounds, config=Config(workload=Workload(
                                    rps=args.rps, duration_s=args.duration, warmup_s=1), seed=args.seed).to_dict()),
                  results=results, equivalent=True,
                  speedup=results["full"]["median_seconds"] / results["summary"]["median_seconds"],
                  peak_traced_reduction_pct=100 * (1 - results["summary"]["memory"]["peak_traced_bytes"] /
                                                   results["full"]["memory"]["peak_traced_bytes"]))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    lines = ["# Local summary benchmark", "", f"Recorded: {report['measured_at']}", "",
             f"Workload: {args.rps:g} offered requests/s, {args.duration:g} simulated seconds, "
             f"1-second warmup, seed {args.seed}; {args.rounds} timing repetitions per path.", "",
             "| Path | Median runtime (s) | Peak traced Python allocations (MiB) |",
             "| --- | ---: | ---: |"]
    for mode in results:
        lines.append(f"| {mode} | {results[mode]['median_seconds']:.4f} | "
                     f"{results[mode]['memory']['peak_traced_bytes'] / 2**20:.3f} |")
    lines += ["", f"Runtime ratio (full / summary): {report['speedup']:.3f}x. "
              f"Peak traced allocation reduction: {report['peak_traced_reduction_pct']:.1f}%.", "",
              "All timing/memory samples passed metric-equivalence checks (relative/absolute tolerance 1e-12).", "",
              f"Platform: {platform.platform()}; CPU: {platform.processor()}; logical CPUs: {os.cpu_count()}.",
              f"Python: {platform.python_version()}.", "",
              "Timing excludes tracing/profiling and process startup. Memory is one tracemalloc sample "
              "per path, not RSS or container memory. These are local observations for one workload, "
              "not production throughput or user-capacity claims.", "",
              f"[Raw samples, complete config, and profiles]({args.output.name}).", ""]
    args.output.with_suffix(".md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("equivalent", "speedup", "peak_traced_reduction_pct")}, indent=2))
    print(f"Report: {args.output}")


if __name__ == "__main__":
    main()
