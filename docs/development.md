# Development guide

## Development and tests

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

The suite covers the simulation engine, theoretical validation, challenges and scoring, progress import/export, run persistence and comparison, and Streamlit save/restore/delete flows. Simulation-heavy tests can take several minutes. CI also covers workload limits, authentication gates, job ownership, the C++ kernel, and disposable distributed services.

### Continuous integration

[GitHub Actions](https://github.com/ARB726/system-design-simulator/actions/workflows/ci.yml)
runs automatically on pushes and pull requests, and can be started manually from the Actions tab.
Core tests run on Python 3.10 and 3.12; Streamlit interaction tests run separately
on Python 3.12 using AppTest, without a browser or a running web server.

The workflow checks Python syntax, caches pip downloads, and uploads JUnit XML test reports
for seven days, including reports from failing test runs. New commits cancel outdated runs
for the same branch or pull request. CI uses disposable service data and read-only repository permissions; no production secrets are required. A dedicated job compiles C++, exercises PostgreSQL/Redis with a real worker, and builds and smoke-tests the Docker image.

Run the same test groups locally:

```bash
python -m pytest -m "not ui" -q
python -m pytest -m ui -q
```

## Project structure

| Path | Responsibility |
| --- | --- |
| `app.py` | Streamlit entry point, controls, tabs, and simulation orchestration |
| `sim/config.py` | Configuration dataclasses, presets, capacity estimates, and costs |
| `sim/engine.py` | SimPy engine, request routing, tiers, queues, shards, and chaos events |
| `sim/analysis.py` | Timelines, aggregate results, and rule-based findings |
| `sim/charts.py` | Plotly architecture diagrams, replay, and experiment charts |
| `sim/history.py` | SQLite/PostgreSQL snapshots and deterministic run comparisons |
| `sim/auth.py`, `sim/jobs.py`, `sim/worker.py` | OIDC ownership, bounded job admission, and Celery workers |
| `sim/execution.py`, `sim/job_ui.py` | JSON worker protocol and nonblocking UI polling |
| `sim/limits.py` | Server-side workload and allocation limits |
| `native/mmc.cpp`, `sim/native.py` | C++ validation kernel and Python adapter |
| `Dockerfile`, `compose.yml` | Web/worker images, health checks, and service deployment |
| `sim/run_library_ui.py` | Save, restore, delete, export, and comparison controls |
| `sim/challenges.py` | Challenge definitions, design knobs, hidden checks, and scoring |
| `sim/predict.py` | Prediction scoring |
| `sim/progress.py` | XP, badges, stars, levels, and progress import/export |
| `sim/experiments.py`, `sim/theory.py` | Parameter sweeps and queueing-theory validation |
| `sim/themes.py`, `.streamlit/config.toml` | Visual themes and industry labels |
| `sim/sharecard.py` | PNG share-card generation |
| `tools/optimize.py`, `data/optima.json` | Offline reference-design generation and stored results |
| `tests/` | Engine, application, persistence, and regression tests |

## Multi-user deployment and C++

See [docs/production.md](production.md) for Docker Compose startup, OIDC configuration,
worker scaling, storage ownership, operating limits, backups, and rollout verification.

The optional C++17 M/M/c event kernel accelerates the Validation lab. The full topology
engine remains SimPy. Build and measure it with:

```bash
python tools/build_native.py
python tools/benchmark_native.py
```

The Docker image includes the compiled kernel. No native compiler is needed to run the
original Python-only demo.
