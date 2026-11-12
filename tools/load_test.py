"""Bounded closed-loop load against disposable Redis/Celery workers (not the UI)."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import logging
import math
from pathlib import Path
import sys
import time
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sim import jobs
from sim.config import Config, Workload


def percentile(values, fraction):
    values = sorted(values)
    return values[max(0, math.ceil(len(values) * fraction) - 1)] if values else None


def run_one(index, *, run_id, batch_every, timeout, config):
    kind = "sweep_load" if batch_every and (index + 1) % batch_every == 0 else "simulate"
    payload = {"config": config}
    if kind == "sweep_load":
        payload["values"] = [10, 20, 40]
    owner = f"loadtest:{run_id}:{index}"
    start = time.monotonic()
    try:
        job_id = jobs.submit(kind, payload, owner)
        while time.monotonic() - start < timeout:
            state, result = jobs.poll(job_id, owner)
            if state == "complete":
                return dict(kind=kind, outcome="failed" if result.get("error") else "complete",
                            elapsed_s=time.monotonic() - start, metrics=result.get("job_metrics", {}))
            time.sleep(0.2)
        return dict(kind=kind, outcome="timeout", elapsed_s=time.monotonic() - start)
    except jobs.JobError:
        return dict(kind=kind, outcome="unavailable", elapsed_s=time.monotonic() - start)


def summarize(records, elapsed):
    report = dict(jobs=len(records), elapsed_s=elapsed,
                  completed_per_second=sum(r["outcome"] == "complete" for r in records) / elapsed,
                  outcomes={outcome: sum(r["outcome"] == outcome for r in records)
                            for outcome in ("complete", "failed", "timeout", "unavailable")}, queues={})
    for kind in sorted({r["kind"] for r in records}):
        group = [r for r in records if r["kind"] == kind and r["outcome"] == "complete"]
        stats = {"completed": len(group)}
        for metric in ("queue_wait_s", "execution_s", "result_bytes"):
            values = [r.get("metrics", {}).get(metric) for r in group]
            values = [value for value in values if value is not None]
            stats[metric] = dict(p50=percentile(values, .5), p95=percentile(values, .95))
        report["queues"][kind] = stats
    return report


def main():
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", type=int, default=20)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--batch-every", type=int, default=4, help="0 disables batches")
    parser.add_argument("--timeout", type=float, default=240)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not (1 <= args.jobs <= 10000 and 1 <= args.concurrency <= 128
            and args.batch_every >= 0 and math.isfinite(args.timeout) and 0 < args.timeout <= 900):
        parser.error("Use 1–10000 jobs, 1–128 clients, nonnegative batch interval and timeout in (0, 900].")
    config = Config(workload=Workload(rps=20, duration_s=10, warmup_s=1)).to_dict()
    run_id = uuid4().hex
    before = jobs.queue_snapshot()
    start = time.monotonic()
    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        records = list(executor.map(lambda index: run_one(
            index, run_id=run_id, batch_every=args.batch_every, timeout=args.timeout, config=config),
            range(args.jobs)))
    report = summarize(records, time.monotonic() - start)
    report["snapshot_before"] = before
    report["snapshot_after"] = jobs.queue_snapshot()
    report["parameters"] = dict(jobs=args.jobs, concurrency=args.concurrency,
                                batch_every=args.batch_every, timeout=args.timeout, config=config)
    output = json.dumps(report, indent=2)
    print(output)
    if args.output:
        args.output.write_text(output + "\n", encoding="utf-8")
    return 0 if report["outcomes"]["complete"] == args.jobs else 1


if __name__ == "__main__":
    raise SystemExit(main())
