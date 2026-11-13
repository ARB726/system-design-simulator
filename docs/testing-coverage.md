# Test coverage and remaining gaps

## Added checks

`tests/test_limits.py` contains 17 cases for invalid tier settings, malformed chaos events, overlapping traffic-spike budgets, the eight-event boundary, optional queue/time limits, and integer replica loss. Running this file with branch coverage gives **100% statement and branch coverage for `sim/limits.py`** (61 statements, 34 branch destinations). This is a module-specific result, not whole-project coverage or proof of every numeric combination.

`native/test_mmc.cpp` directly exercises the real C++ Kernel: simultaneous arrivals on multiple servers, FCFS scheduling, warmup work affecting measured requests, fractional server counts, invalid numeric arguments, unsorted and zero/nonfinite service traces, request ceilings, overflow, and empty measurement windows. CI compiles and executes it with warnings as errors. Existing Python native tests additionally exercise the compiled CLI and compare stochastic results to queueing theory.

## Remaining coverage gaps

- **Visual browser behavior:** Streamlit AppTest checks widget behavior, but does not render CSS. Dark-theme contrast, hover/focus effects, animation timing, reduced-motion preferences, and mobile layout still need real-browser checks.
- **C++ branch coverage:** The new harness passes, but no gcov/LLVM coverage percentage has been measured. CLI usage/parse permutations, aggregate sum overflow, exact numeric upper boundaries, and the stochastic generation loop are not exhaustively exercised by this harness. Existing integration tests cover only some of these paths.
- **Services and authentication:** Unit tests use substitutes for several job/auth paths; actual Redis/PostgreSQL tests require the service-enabled CI job. Real identity-provider redirects, browser sessions, multi-user isolation through a deployed UI, and network outages need deployment-level tests.
- **Concurrency and operational behavior:** Small tests cannot establish fairness, tail latency, worker-crash recovery under sustained load, or behavior during Redis/PostgreSQL outages. Existing scaling/service tests and load tooling cover selected scenarios, not all failure interleavings.
- **Simulator state space:** Named presets and theory comparisons sample the model. They do not exhaust all combinations of overlapping chaos events, hot shards, queue saturation, caching, seeds, and timeouts. Property-based tests would broaden this coverage.

## Reproduce

```powershell
python -m pip install coverage
python -m coverage run --branch --source=sim.limits -m pytest tests/test_limits.py -q
python -m coverage report -m
g++ -std=c++17 -Wall -Wextra -Werror native/test_mmc.cpp -o .local/bin/test-mmc.exe
./.local/bin/test-mmc.exe
```

For a broader Python report, run `python -m coverage run --branch --source=sim -m pytest -m "not ui and not services and not native" -q`, followed by `python -m coverage report -m`. That selection deliberately excludes UI, native integration, and external-service tests; report its scope alongside any percentage. C++ coverage needs a separate instrumented compiler build.

## Expanded boundary regression suite

`tests/test_edge_cases.py` adds 47 distinct test functions for prediction bucket boundaries and feedback, star/level thresholds, malformed progress imports, queueing-theory identities, and native subprocess success/timeout/OS/JSON failures.

Verified locally: **73 tests passed** across `test_edge_cases.py`, `test_limits.py`, and `test_progress.py`. With branch instrumentation, `sim.limits`, `sim.native`, `sim.predict`, `sim.progress`, and `sim.theory` each have **100% statement and branch coverage** (277 statements and 112 branch destinations combined). The deterministic C++ harness also passed again. The native wrapper tests include mocked failures; they do not replace real-binary integration tests.

Reproduce the focused report with:

```text
python -m coverage run --branch --source=sim.predict,sim.progress,sim.theory,sim.native,sim.limits -m pytest tests/test_edge_cases.py tests/test_limits.py tests/test_progress.py -q
python -m coverage report -m
```

This is not a whole-project coverage claim. Engine, analysis, charts, experiments, jobs, persistence, UI, production services, and C++ instrumentation remain outside this focused measurement. The wider core run must finish before reporting its percentage. The behavioral gaps above still apply even where branch coverage is 100%.

## Expanded C++ tests

`native/test_mmc.cpp` now has 34 named test functions, including direct kernel checks and CLI tests with captured standard streams. It verifies FCFS/parallel service, idle periods, exact warmup and request-limit boundaries, numeric parsing, malformed trace inputs, response overflow, invalid workload/seed values, arrival budgets, JSON output fields, and deterministic seeds. All 34 passed with `-std=c++17 -Wall -Wextra -Werror`. Checks throw on failure rather than relying on `assert`, so release builds retain validation. The existing CI step runs the expanded suite automatically.

This does not establish a measured C++ coverage percentage; compiler-instrumented coverage and sanitizer runs remain separate checks.
