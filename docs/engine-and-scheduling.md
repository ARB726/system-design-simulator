# Engine profiling and dynamic sweep scheduling

## Profile before changing the event model

`tools/profile_engine.py` records cProfile summaries for normal traffic, overload, retries, and queued writes. Each case has a fixed seed and records its full configuration, package versions, metrics, and the functions with the most own/cumulative time. A separately timed unprofiled run checks that profiling does not change results. cProfile adds substantial overhead; its times describe where work occurs, and overlapping cumulative times cannot be summed.

The retry profile found 97,051 calls to `arrival_limit`, repeatedly reading the same environment setting. The engine now snapshots that operational budget once after configuration validation and reuses it for arrival-proposal and request-attempt checks. A new simulation reads the current setting again. Active runs retain their original budget; changing an environment variable does not change an already-created simulation. Budget comparisons, random-number calls, and SimPy event scheduling remain unchanged.

SimPy scheduling, generator resumption, and the engine's serve/attempt/request paths remain major costs. Replacing timeout or resource events would need a separate model-equivalence investigation; this change leaves those semantics intact.

## Give available workers the next point

Previously each child received a fixed round-robin chunk. If expensive points landed in the same chunk, the other child could finish early and sit idle. The new scheduler starts a bounded number of persistent Python children and sends each one another point after it finishes its current point. Each child constructs a new simulation with that point's configuration and seed; only the interpreter is reused.

The private subprocess protocol is one JSON request and response per line. Reader threads handle Windows pipes while simulation CPU work stays in child processes. Stderr goes to a temporary file rather than a pipe that might fill. The original single-document entry point remains available for compatibility and the static-scheduler benchmark.

Results retain input order, even if completion order differs. Progress updates after each completed point. The parent validates the whole batch before creating children, and children validate each received configuration. Existing point, arrival/attempt, worker-count, and aggregate batch limits apply. Celery still runs points sequentially inside its existing worker; this does not add nested subprocess pools to distributed execution.

Each child has one 180-second wall-clock lifetime budget including startup and every assigned point. New points do not reset the budget. Timeout, early exit, malformed response, or a failing progress callback closes and reaps all children before propagating the error. Worker reuse and asynchronous pipes add lifecycle complexity, covered by explicit cleanup tests.

## Reproduce

Run benchmarks without competing test runners or application servers. Scheduling measurements include interpreter startup and JSON communication. Both old and new schedulers use the current engine, isolating scheduling from the separate budget-lookup change. All measured point results must match the sequential path exactly.

```powershell
./.venv/Scripts/python.exe tools/profile_engine.py --output .local/engine-profile.json
./.venv/Scripts/python.exe tools/benchmark_hot_paths.py --baseline-ref 87157cb --suite resilience --rounds 5 --output .local/engine-budget.json
./.venv/Scripts/python.exe tools/benchmark_scheduling.py --baseline-ref 87157cb --rounds 3 --output .local/scheduling.json
./.venv/Scripts/python.exe -m pytest tests/test_batch_scheduling.py tests/test_engine_budget.py tests/test_experiments.py tests/test_resilience.py tests/test_limits.py -q
```

Engine timing samples begin after explicit garbage collection so one path does not inherit the previous path's cyclic SimPy event graphs; automatic collection remains enabled during execution. Process CPU time and wall time are recorded separately. Measurements cover one machine and one seed per workload; they are observations, not production capacity claims or confidence intervals.

Regression tests compare full request tables, resource samples, write lag, traffic counters, and exact summaries against the previous repeated-budget behavior across two seeds. Scheduling tests use real children to verify reuse, seeded point equality, timeout/crash/malformed-response handling, and process reaping. Deterministic synchronization tests show that a fast child receives remaining points while a slow child is still occupied, enforce worker bounds, preserve input order, and check cleanup after worker/progress failures. Lifetime and runtime-budget checks protect the operational bounds.
