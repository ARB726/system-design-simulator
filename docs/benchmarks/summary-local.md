# Local summary benchmark

Recorded: 2026-11-12T00:37:49.365991+00:00

Workload: 500 offered requests/s, 20 simulated seconds, 1-second warmup, seed 7; 3 timing repetitions per path.

| Path | Median runtime (s) | Peak traced Python allocations (MiB) |
| --- | ---: | ---: |
| full | 1.9193 | 3.366 |
| summary | 1.8622 | 0.535 |

Runtime ratio (full / summary): 1.031x. Peak traced allocation reduction: 84.1%.

All timing/memory samples passed metric-equivalence checks (relative/absolute tolerance 1e-12).

Platform: Windows-10-10.0.26200-SP0; CPU: Intel64 Family 6 Model 142 Stepping 12, GenuineIntel; logical CPUs: 8.
Python: 3.10.11.

Timing excludes tracing/profiling and process startup. Memory is one tracemalloc sample per path, not RSS or container memory. These are local observations for one workload, not production throughput or user-capacity claims.

[Raw samples, complete config, and profiles](summary-local.json).
