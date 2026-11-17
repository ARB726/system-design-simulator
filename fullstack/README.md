# Systems Lab — full-stack edition

A React/Next.js interface, FastAPI API, durable background worker, and persistent database around the original Python/SimPy engine. The Streamlit application remains available separately.

**Live application:** https://d11ry0yeilwlgs.cloudfront.net. Select **Run simulation**, then use **Sign up** on the hosted sign-in page to create your application login and confirm your email. This login is separate from your AWS project sign-in.

## Run after AWS credits expire

Nothing in local mode needs AWS, a subscription, or an API key. Python 3.12 and Node 20.9+ are required to install/build; after building, only Python is needed to run the exported website.

From the repository root on Windows:

```powershell
py -3.12 -m venv .venv
./.venv/Scripts/python.exe -m pip install -r fullstack/backend/requirements.txt
cd fullstack/frontend
npm ci
npm run build
cd ../..
./.venv/Scripts/python.exe tools/run_fullstack.py
```

Open **http://127.0.0.1:8080**. Choose **Run simulation**, create a local account, then submit the experiment. Passwords need at least 12 characters. The worker and API start together; Ctrl+C stops both. Changes and completed results persist in `data/fullstack.db`. Back up that database and `data/fullstack-session.key` with the application stopped. Keep these files private.

The portable ZIP includes the already-built website in `fullstack/frontend/out`. If that folder is present, skip the Node/npm build steps: install the Python backend requirements once, then double-click `Start-SystemsLab.cmd` on Windows or run `tools/run_fullstack.py`. The source is included for future editing and rebuilding.

On macOS/Linux use `python3 -m venv .venv` and `.venv/bin/python` in place of Windows commands. Optional flags: `--port 8081 --api-port 8001`. Local mode binds to localhost. Its account system is intended for use on your computer; cloud hosting uses Cognito.

## What is implemented

- Architecture canvas, engine presets, workload/capacity/component controls, failure injection, seed selection, and full JSON configuration import/export.
- Persistent asynchronous experiments with queued/running/completed/failed states; a two-active-experiment limit per user and server-side workload limits.
- Throughput, p50/p95/p99, latency histograms, queue pressure, async write lag, engine findings, and illustrative resource costs.
- Private experiment library, matched-condition comparison warnings, six existing learning challenges and their actual engine grading checks.
- Export experiment results or the latest 100 experiments. Import finished experiment archives locally from the library to preserve cloud results.
- A SQL backend supporting SQLite or PostgreSQL locally. The Docker Compose variant runs PostgreSQL. The AWS variant uses DynamoDB metadata, S3 results, and SQS workers to avoid an always-running RDS instance.

The diagram reflects configured components; it is not a drag-and-drop editor. Challenge grading runs the existing checks and budget rule. Streamlit's specialized replay and multi-seed sweep interfaces remain in the original application. This is a functional migration of the central experiment workflow, not complete UI parity.

## Preserve cloud results before the Free plan ends

1. Wait for all queued/running experiments to finish.
2. Open **Experiment library → Export all** in the cloud website.
3. Start the local app, sign in to a local account, and choose **Import archive** in its library.
4. Select the exported JSON. Results are restored under the local user with new experiment IDs.

Cloud login and local login are separate. Cloud passwords/tokens are not exported. An archive contains configurations and result data, so keep it private. Cloud storage is not a substitute for your own backup. Free plan expiration can disable access to AWS resources; export before expiration.

Local archive imports are limited to 8 MB. For a larger library, export each completed experiment from its results page and import those individual JSON files instead.

## PostgreSQL with Docker (optional)

Build the frontend as above, copy `fullstack/.env.example` to `fullstack/.env`, set two strong unique values, then run:

```powershell
docker compose --env-file fullstack/.env -f fullstack/compose.yml up --build
```

Open http://127.0.0.1:8080. Docker is optional and was not installed on the development machine; the Compose path requires verification on a Docker host. The PostgreSQL volume persists across ordinary restarts. Do not remove it without a backup. For another SQL host, set `DATABASE_URL=postgresql+psycopg://...` for both API and worker, and share `LOCAL_SESSION_SECRET`.

## Develop and test

Run the API with `python -m uvicorn fullstack.backend.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers` and the worker with `python -m fullstack.backend.worker`. In `fullstack/frontend`, run `npm run dev`. API documentation: http://127.0.0.1:8000/docs.

```powershell
./.venv/Scripts/python.exe -m pytest tests/test_fullstack.py -q
cd fullstack/frontend
npm run typecheck
npm run build
npm run test:e2e
```

See [AWS deployment](aws/DEPLOY.md) for infrastructure, cost assumptions, validation, deployment, backup, and teardown. `python tools/package_fullstack.py` produces a portable project archive including the prebuilt website when present, without secrets, saved data, installed dependencies, or build caches.
