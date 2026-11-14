# System Design Simulator

[![CI](https://github.com/ARB726/system-design-simulator/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/ARB726/system-design-simulator/actions/workflows/ci.yml)

**Design a system, stress it, and see where it breaks.**

An interactive learning lab for developers practicing system design. Build a simulated architecture, inject failures, and compare throughput, tail latency, reliability, and illustrative monthly cost before choosing a design.

**Stack:** Python, Streamlit, SimPy, Plotly, SQLite. Optional multi-user deployment: PostgreSQL, Redis, Celery, OIDC, and a C++17 validation kernel.

[Try it locally](#quick-start) · [Two-minute walkthrough](#two-minute-walkthrough) · [Engineering case study](docs/performance.md) · [Architecture](docs/architecture.md)

## Engineering highlights

- **Model system behavior:** a discrete-event engine models replicas, caches, CDN hits, sharding, bounded queues, timeouts, and failures. Response latency and asynchronous write-apply lag are measured separately.
- **Optimize without changing results:** the summary execution path reduced peak traced Python allocations by **84.1%** (3.366 to 0.535 MiB) in the [recorded local benchmark](docs/benchmarks/summary-local.md). The workload offered 500 requests/s for 20 simulated seconds; metric-equivalence checks passed at 1e-12 tolerance. This measures Python allocations for one workload, not process memory or production capacity. Median runtime changed from 1.9193 to 1.8622 seconds.
- **Make comparisons explainable:** saved snapshots preserve completed configurations and results; comparisons flag changes in workloads, seeds, and chaos events that could confound conclusions.
- **Separate the engine from delivery:** the same simulation core supports a local demo and an optional authenticated deployment with bounded background jobs and account-owned storage. See the [deployment design](docs/production.md).
- **Validate the model:** queueing-theory checks, regression tests, Streamlit interaction tests, and distributed-service CI cover the engine and its delivery paths. See [test coverage](docs/testing-coverage.md) and the [development guide](docs/development.md).

## Two-minute walkthrough

For an in-app introduction, choose **Start guided walkthrough**. It walks through a cold-cache failure, one capacity change, and a paired comparison across seeds. See the [learning and resilience guide](docs/learning-lab.md) for evidence windows, retry/backoff policies, admission control, and bounded parallel sweeps.

After starting the app locally:

1. In **Sandbox**, choose **Failure: cache goes cold** from **Scenario**, then press **Run simulation**. If prediction mode is enabled, use **Lock prediction and run** to start the run.
2. Inspect the results and replay: follow database pressure and latency as the cache loses effectiveness. Expand **Save this run** and save it as `Baseline`.
3. Increase **Connections per node** under **Database** in the sidebar, keeping the workload, seed, and failure scenario unchanged. Run again and save as `More DB capacity`.
4. Open **Saved runs & compare**. Compare success rate, p95/p99 latency, and monthly cost. Explain whether the extra capacity was worth its cost for this scenario.

For another tradeoff, open **Find your next experiment** and try **Can a queue absorb a burst?** Compare acknowledgement latency with write-apply lag. Selecting a guided experiment replaces the current sandbox settings.

The demo runs locally without an LLM, API key, or cloud account. See the [user guide](docs/user-guide.md) for saved-library access, persistence, and the six-challenge campaign.

## Quick start

Use Python 3.10 or newer. Run the following commands from the repository root.

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

Open the local URL printed by Streamlit, normally `http://localhost:8501`.

The app runs simulations locally in the Python server process. It does not provision cloud infrastructure or send real traffic to external databases, caches, or CDNs.

## Modeling assumptions and limitations

- **Arrivals and service:** Poisson arrivals and exponential service times provide a queueing-theory baseline.
- **Tier behavior:** Workers are released before a request enters the next tier. Queue limits and client timeouts affect completion.
- **Failures and latency:** Timeout, drop, and error outcomes are included in effective latency using the configured timeout. Incomplete work is tracked separately.
- **Async writes:** Acknowledgement occurs after enqueue; apply lag measures when the database receives the write.
- **Retries and admission:** Optional read retries use bounded exponential backoff and jitter; a token bucket can reject excess attempts. Writes are never retried. Attempt amplification and user-visible success are reported separately.
- **Simplifications:** Network transport latency, replica lag, consistency semantics, write idempotency, and cache invalidation are not modeled.
- **Costs:** Prices are illustrative. Results support learning and relative comparisons rather than production capacity estimates.

Queueing behavior is checked against Erlang C / M/M/c formulas. The tests pool multiple seeds and check mean response time against theory; scenario tests cover failures, caching, queues, and sharding.

## Explore the project

| Read | What it explains |
| --- | --- |
| [Architecture](docs/architecture.md) | Application components, request routing, and storage boundaries |
| [Performance case study](docs/performance.md) | Optimization decisions, benchmark methodology, and correctness checks |
| [User guide](docs/user-guide.md) | Saved runs, comparisons, persistence, and challenge scoring |
| [Learning and resilience](docs/learning-lab.md) | Guided experiments, measured evidence, paired seeds, retry storms, and admission control |
| [Development guide](docs/development.md) | Test commands, CI, source map, and native kernel build |
| [Production runbook](docs/production.md) | Optional multi-user deployment, ownership, worker limits, and operations |

## Future directions

Potential next steps include durable classroom progress, job cancellation and richer progress,
retry/backoff and rate-limiting scenarios, multi-region models, and classroom assignments.
Production load tests and operational monitoring should precede public rollout.
