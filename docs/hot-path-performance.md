# Engine hot-path cleanup

The engine now filters chaos events directly instead of allocating an active-event list on each query. Least-queue routing builds only the current minimum-load tie list, avoiding the separate list of every node's load. It preserves ascending tie order, performs the same RNG choice only when a tie exists, and leaves arrival generation and simulation scheduling unchanged.

## Local measurement

Five timing rounds per path, after warming both implementations. Measurement order alternates; imports and equality checks are excluded from timing. Each invocation constructs a fresh simulation. The baseline is revision `1c7ea85` of the engine, loaded with the same configuration module and dependencies as the candidate. All summary metrics matched exactly in every measured run.

| Workload | Baseline median (s) | Candidate median (s) | Baseline / candidate |
| --- | ---: | ---: | ---: |
| Default, 500 offered requests/s | 0.6231 | 0.5969 | 1.044x |
| 32 app replicas, 1,000 offered requests/s | 1.5361 | 1.4140 | 1.086x |
| Overlapping spikes, replica loss, database slowdown | 1.2490 | 1.1440 | 1.092x |

All cases simulate 20 seconds with a 1-second warmup and seed 7. The event case starts at 500 offered requests/s before spikes. Full configurations, dependency versions, platform details, and individual samples are in [the raw report](benchmarks/hot-path-local.json).

These are local in-process observations, not production capacity claims. They do not isolate allocator costs or establish a statistically significant speedup across machines. The benchmark measures summary execution; full-trace rendering and distributed job overhead are outside its scope.

From the repository root, with development dependencies installed:

```bash
python tools/benchmark_hot_paths.py --baseline-ref 1c7ea85 --rounds 5 --output .local/hot-path-benchmark.json
python -m pytest tests/test_hot_paths.py tests/test_summary.py tests/test_native.py -q
```

Build the optional native binary before running the native Python tests; otherwise pytest skips them. See the [production runbook](production.md) for native setup.

## Correctness coverage

- Python routing tests compare choices and RNG state against the previous algorithm across changing node loads, ties, subranges, and all routing strategies.
- Event tests cover overlaps, empty lists, and start/end boundaries.
- Every built-in preset runs with two seeds against the old algorithms, comparing request tables, sampled utilization, write lag, warnings, and summary metrics exactly. Fixtures compress scenario time to eight seconds while retaining load and event order.
- Python feeds identical deterministic traces into SimPy and C++ for four server counts and three warmup values, comparing request counts and mean waiting/response times.
- C++ compares the heap kernel against an independent linear-scan scheduler after each of 24,000 arrivals, covering queue growth, ties, idle periods, and warmup boundaries. No native production code changed.

Validation on Windows/Python 3.12: **69 Python tests passed**. MSVC C++17 compilation with `/W4 /WX /O2`: **35 C++ tests passed**.
