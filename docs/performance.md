# Exact summaries with less retained simulation data

## Problem and decision

Load and replica sweeps previously executed the full simulation pipeline for every
point, retaining request tuples and constructing a sorted pandas request table,
utilization samples, and drained-write lag history. The sweeps only consumed six
aggregate statistics: offered/served throughput, success rate, and p50/p95/p99 latency.

The compact path runs the same request-routing, resource, timeout, and failure logic.
It keeps counters and one float64 effective-latency value per post-warmup arrival,
then calculates exact linear-interpolated quantiles. It skips replay sampling,
request-table construction/sorting, and write-lag retention. There is no percentile
approximation. This remains O(n) storage, rather than a constant-memory algorithm.

`run_summary(config)` is used by load and replica sweeps. `run(config)` still returns
full traces for interactive simulation, replay, diagnosis, grading, and theory validation.
Those consumers need information beyond the six sweep metrics; switching them would
change their behavior. Workers return the same sweep table schema as before.

## Local measurement

See the [measured result table](benchmarks/summary-local.md) and
[raw measurements, configuration, and profiles](benchmarks/summary-local.json).
The baseline is the full-trace path
in the same revision, followed by its original `_quick` reduction; the candidate is
`run_summary`. It is a comparison of equivalent sweep-point calculations, not a
historical benchmark of a different engine revision.

## Reproduce and inspect

From the repository root, with project dependencies installed:

```bash
python tools/benchmark_summary.py --rounds 3 --rps 500 --duration 20 --seed 7 --output .local/summary-benchmark.json
python -m pytest tests/test_summary.py -q
```

Every sample runs in a fresh subprocess. Imports and a small initialization warmup
are excluded from timing. Each child warms both paths; each measured operation uses
a new simulation. Mode order alternates across timing rounds. Separate subprocesses
measure traced allocations and collect cumulative-time profiles, keeping instrumentation
out of the timing samples. The script checks metric equivalence for timing/memory
samples and records the complete config, Python/platform/CPU information, individual
samples, and medians. A configurable seed makes the request workload reproducible.
The command writes JSON plus a Markdown result table alongside it.

## Correctness details

Failures use the same configured timeout penalty as the full path. Without a timeout,
the full path uses the largest raw latency from the entire run, including warmup;
the compact path tracks that maximum even for requests excluded from steady-state
statistics. Unfinished requests retain their observed lower-bound latency and count
as offered but not successfully served. Both paths simulate the same drain horizon.

Regression checks cover two seeds across baseline traffic, overload, absent timeouts,
asynchronous writes, replica failures/cold caches, CDN/shards/read replicas, an empty
measurement window, shared queues, and app-only execution. Additional checks compare
both sweep tables, verify trace artifacts are not retained, and exercise the warmup
maximum failure penalty directly. Comparisons use tight floating-point tolerances.

## Limits and next experiments

Tracemalloc measures peak traced Python allocations, not process RSS, container memory,
or all native allocations. Memory is sampled once per path; timing uses three repetitions
of one seed and workload. These local results are not confidence intervals or estimates
of concurrent-user capacity. Host activity, platform, traffic mix, and overload change
the outcome. Run larger workloads and multiple seeds on deployment hardware before
setting worker limits. No wall-clock threshold is enforced in CI.

Profiling identifies SimPy event processing as the main runtime cost. Removing unused
artifacts primarily reduces retained data; it does not eliminate event execution.
Potential next experiments are compact output storage for interactive replay and
parallel scheduling of independent sweep points. Any percentile sketch or reduced
replay fidelity would require an explicit accuracy contract and separate validation.

For job-level throughput, queue latency, and Redis measurements, use the separate
[mixed-load harness](production.md#queue-metrics-and-repeatable-load-testing).
