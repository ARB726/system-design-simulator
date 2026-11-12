# Multi-user deployment

This deployment adds OIDC sign-in, account-scoped PostgreSQL run libraries, Redis/Celery
background jobs, and an optional C++ validation engine. It is a deployable foundation;
operating it publicly also requires identity-provider setup, TLS, backups, monitoring,
and load testing for your expected traffic.

## Service architecture

```mermaid
flowchart LR
    User[Browser] --> Proxy[TLS reverse proxy]
    Proxy --> Web[Streamlit web]
    Web <-->|Sign in| OIDC[OIDC provider]
    Web <-->|Account-scoped saved runs| PG[(PostgreSQL)]
    Web -->|Bounded job submission| Redis[(Redis broker and results)]
    Redis --> Workers[Celery worker processes]
    Workers --> Python[SimPy full topology engine]
    Workers --> CPP[C++ M/M/c validation kernel]
    Workers -->|JSON results| Redis
    Redis -->|Poll status and results| Web
```

The broker and database are private container-network services. There is no public job
submission API. Web and worker services use the same application image. Scaling workers
adds simulation CPU capacity without running simulations in Streamlit request threads.

## Start the stack

Install Docker with the Compose plugin. From the repository root:

```bash
cp .env.example .env
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
python -c "import secrets; print(secrets.token_hex(32))"
```

On PowerShell use `Copy-Item` instead of `cp` if preferred. Put a generated hex password
in `.env` as `POSTGRES_PASSWORD`. Generate a separate long random `cookie_secret` for the
OIDC secrets file. Fill in the provider's client ID, client secret, and metadata URL.
Register the exact callback URL, ending in `/oauth2callback`, with your provider.
The example uses Google's discovery endpoint; use your provider's endpoint if different.

For local evaluation the callback is `http://localhost:8501/oauth2callback`. For public
hosting change it to your HTTPS domain and configure your reverse proxy to forward
WebSockets. Compose binds the app to `127.0.0.1:8501` so it is reachable through a proxy
on the host, while Redis and PostgreSQL have no published ports.

```bash
docker compose config --quiet
docker compose up --build -d
docker compose ps
docker compose logs -f web worker
```

Open `http://localhost:8501` and sign in. The app fails closed: unauthenticated users
cannot run experiments or read libraries. Missing provider configuration must be fixed
before sign-in works. Secrets and `.env` are excluded from Git and the image build context.
The web container runs as UID 10001; grant that UID read access to the mounted secrets
file without making it writable by the container.

Docker is not required for the original local demo:

```bash
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

That mode uses SQLite, link-based library access, and synchronous Python execution.
It is distinct from the authenticated multi-user configuration.

## Scaling and bounds

```bash
docker compose up -d --scale worker=3
docker compose up -d --scale batch-worker=2
```

`worker` consumes simulations/replays and legacy `celery` messages. `batch-worker`
consumes grading, sweeps, and validation. Both pools start by default; budget resources
for both. Dedicated pools reserve interactive execution slots, but admission limits
remain shared: batches filling the global budget can still reject interactive jobs.

Each worker container runs two prefork processes, so three containers offer six task
execution slots. Match this to available CPU and memory; adding workers beyond host
capacity can increase latency. Each container has a memory limit and recycles child
processes after 20 jobs. Only Linux prefork workers provide the configured hard task
timeouts; use the containers for workers on Windows.

| Control | Compose default |
| --- | --- |
| Simultaneous queued/running jobs per account | 2 |
| Total admitted queued/running jobs | 32 |
| Queue expiry before task start | 600 seconds |
| Soft / hard worker time limit | 165 / 180 seconds |
| Redis admission lease after a lost worker | 800 seconds |
| Transient result retention | 1 hour |
| Arrival proposal limit per simulation | 500,000 |
| Saved snapshots per account | 100 |

Admission is atomic in Redis. Per-user limits use the authenticated issuer/subject identity,
not a browser-supplied library ID. Normal completion releases capacity; expired leases
recover capacity after crashes or hard timeouts. Request counts, rates, resource counts,
event counts, and finite numeric inputs are validated server-side. Large batches are
bounded, and the worker's time limit also applies to the entire batch.

Results in Redis are temporary. Save important runs to PostgreSQL before their results
expire. An expired job can be retried. Browser session state and pending UI selections
are not durable; reopening a browser may require resubmission. PostgreSQL snapshots are
durable independently of those transient jobs. Campaign XP remains session/JSON based.

The default deployment has one Streamlit instance. To add web replicas, use a load
balancer with WebSocket support and sticky sessions, identical OIDC cookie secrets,
shared PostgreSQL/Redis settings, and per-replica memory budgets. Test reconnect and
session behavior before routing real users across replicas.

## Storage and ownership

`SYSDESIGN_DATABASE_URL` selects PostgreSQL; without it, `SYSDESIGN_RUN_DB` selects a
SQLite file. Existing SQLite libraries are not automatically migrated into accounts.
Production library ownership derives from verified OIDC `iss` and `sub` claims. URL
parameters cannot override it. Deleting or selecting another account's snapshot is
scoped at the storage query boundary. PostgreSQL advisory locks protect the 100-run
capacity check under concurrent requests.

Compose persists PostgreSQL and Redis in named volumes. Back up PostgreSQL regularly
and rehearse restoration. For example, from a shell on the Docker host:

```bash
docker compose exec -T postgres pg_dump -U sysdesign -d sysdesign > sysdesign-backup.sql
```

Use a secure backup destination. `docker compose down` keeps volumes; deleting volumes
deletes their data. Redis uses append-only persistence and a `noeviction` memory policy
to protect broker data. If it reaches its memory budget, submissions/results can fail;
monitor memory and tune result retention, workload limits, and capacity together.

## C++ validation engine

The image compiles `native/mmc.cpp` into `sysdesign-mmc`. This is a C++17 FCFS M/M/c
event kernel with an O(log c) min-heap and O(c) server state. It is a standalone executable,
so no CPython ABI or binding dependency is required. Python passes bounded numeric
arguments without a shell, enforces a subprocess timeout, and reads a JSON result.

Choose **C++ event kernel** in the Validation tab. Full CDN/cache/sharding/chaos
simulations still use SimPy. The C++ option returns aggregate queueing validation
metrics; it does not provide the full engine's per-request traces or replay.

Build and benchmark outside Docker:

```bash
python tools/build_native.py
python -m pytest -m native -q
python tools/benchmark_native.py
```

Use g++/clang++, set `CXX`, or install the optional `ziglang` compiler package on Windows.
The binary is built under `.local/bin` and is not committed. `SYSDESIGN_NATIVE_BINARY`
can point to a deployed binary elsewhere. If no binary is installed, the UI offers
the original Python/SimPy validation path.

Native correctness tests cover an exact FCFS trace, seeded repeatability, input rejection,
and agreement with Erlang C over multiple seeds. The two engines use different random
number generators and are statistically comparable, not bit-for-bit identical. Native
requests arriving before the horizon are measured through completion, while SimPy's
finite trace can include incomplete requests at the horizon. Compare long steady-state
runs rather than expecting identical transient samples.

## Verification and operation

GitHub Actions builds the C++ kernel with warnings as errors, tests Redis admission under
concurrency, checks PostgreSQL isolation and capacity, starts a real Celery worker, and
builds/smoke-tests the application container. Local service tests require disposable services:

```bash
export SYSDESIGN_TEST_DATABASE_URL=postgresql://user:password@localhost/test_database
export SYSDESIGN_TEST_REDIS_URL=redis://localhost:6379/15
python -m pytest -m services -q
```

Use a dedicated Redis database: the worker test starts a real consumer. Never point these
tests at a production broker. Container health checks cover PostgreSQL, Redis, worker
responsiveness, and Streamlit liveness. They do not replace an authenticated end-to-end
probe that submits a small job and verifies its saved result.

Before public rollout, verify the OIDC callback over HTTPS, user isolation, queue behavior
under your target concurrency, result expiry, worker termination, database restoration,
and alerts for queue depth, failure rate, memory, and disk usage. Set operational SLOs
from those measurements. No production concurrency or availability claim is made by
the included local benchmark or numerical tests.

## Queue metrics and repeatable load testing

Worker logs include JSON `job_finished` events with queue wait, execution seconds,
job ID, workload kind, queue, and complete/failed outcome. `job_result` reports UTF-8
JSON payload bytes before metrics are attached. Submission events distinguish
accepted, rejected, and unavailable submissions. Owners and workload payloads are
excluded. Aggregate these events in a log collector for latency and failure alerts.
Queue wait uses wall clocks across hosts: synchronize clocks. Execution duration uses
a monotonic clock and excludes result-backend persistence. Hard-killed workers cannot
emit final events; monitor missing completions and admission lease expiry too.

Run the harness against a disposable, configured copy of the stack:

```bash
docker compose exec -T web python tools/load_test.py --jobs 40 --concurrency 4 --batch-every 4
docker compose up -d --scale worker=3 --scale batch-worker=2
docker compose exec -T web python tools/load_test.py --jobs 40 --concurrency 4 --batch-every 4
```

This submits fixed-seed simulations and three-point sweeps using unique test owners.
It benchmarks internal queues/workers, excluding OIDC, Streamlit, and PostgreSQL;
it does not establish user capacity. Each client waits for its job before submitting
another (closed-loop load). Save JSON with `--output PATH` or redirect stdout on the
host. Reports include throughput, outcomes, per-workload p50/p95 wait/runtime/result
bytes, workload parameters, and before/after admitted counts, ready queue depths,
and Redis process memory. Ready counts exclude reserved/running tasks and assume
default Redis priorities. Redis memory covers the whole server, not worker peak memory.

The tool exits nonzero for failed, timed-out, or unavailable jobs. Unavailable includes
busy admission and infrastructure/expiry errors; submission logs distinguish them.
Timeouts do not cancel jobs. Let workers drain before the next run. Results/ownership
keys expire normally. Keep admission limits fixed when comparing worker counts;
increase limits only after measuring queue delay and CPU/memory headroom.

For upgrades, deploy new consumers before producers and drain old workers before
replacement: old workers cannot accept the new timing keyword. The interactive pool
consumes legacy `celery` messages. Standalone workers without `-Q` consume all three
queues for development/testing.
