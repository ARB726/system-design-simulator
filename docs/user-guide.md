# User guide

For the guided first run, bottleneck evidence, multi-seed comparisons, retry/backoff controls, and parallel sweeps, see [Learning and resilience](learning-lab.md).

## Save, compare, and explain

1. Choose **Sandbox**, configure a scenario, and run the simulation.
2. Under **Results**, expand **Save this run**, give it a name such as `Baseline`, and save it.
3. Change the architecture, press **Run simulation**, and save a candidate.
4. Open **Saved runs & compare** and select the baseline and candidate.

Comparisons show served throughput, success rate, p95/p99 latency, monthly cost, configuration differences, bottleneck changes, and measured tradeoffs. Warnings identify different workloads, chaos events, or seeds, and remind you that one stochastic run does not establish a reliable improvement.

Each snapshot preserves the completed run's configuration, summary, findings, and cost at save time. Pending sidebar edits are excluded until simulated. You can load a saved design back into the sandbox, download snapshots and comparison reports as JSON, or delete a selected run.

### Library access and persistence

The following describes local demo mode. In the [multi-user deployment](production.md), libraries belong to signed-in OIDC identities and use shared PostgreSQL storage; URL parameters cannot select another account.

- **Bookmark the full URL**, including `?library=...`, to reopen your library after a browser or app restart.
- Anyone with that URL can read and edit the library. This is link-based access, not account authentication.
- Each library can hold up to **100 runs**.
- The default database is `.local/runs.sqlite3`, which is excluded from Git.
- Saved runs persist while the database file persists. Downloaded JSON reports preserve the results; the app does not currently import saved-run files.
- Challenge XP and badges use the separate **Save progress / Load progress** JSON controls.

To choose a persistent database location, set `SYSDESIGN_RUN_DB` before starting the app:

```powershell
# Windows PowerShell: use an existing persistent directory.
$env:SYSDESIGN_RUN_DB = 'C:\data\sysdesign\runs.sqlite3'
python -m streamlit run app.py
```

```bash
# macOS / Linux: use an existing persistent directory or mounted volume.
export SYSDESIGN_RUN_DB=/data/sysdesign/runs.sqlite3
python -m streamlit run app.py
```

The server process must be able to write to the directory. Ephemeral hosts can discard the database during redeployment. SQLite mode is designed for one app instance with durable storage. Use the PostgreSQL/worker deployment for shared multi-user storage.

## Challenge campaign

Earn a star on a challenge to unlock the next.

| Challenge | Industry | Main lesson |
| --- | --- | --- |
| Launch day: URL shortener | Social | Horizontal scaling, CDN/cache tradeoffs, and replica failures |
| Cache failure drill | E-commerce | Size the database for cache misses, not just the happy path |
| Write storm: chat service | Social | Async queues, write lag, and database capacity |
| Flash sale: checkout | E-commerce | Burst traffic, budgets, and database slowdowns |
| Payments ledger: the hot account | Fintech | Hot keys, sharding limits, and synchronous writes |
| Game launch: the leaderboard | Gaming | Reducing downstream load with a CDN |

Scores combine up to **70 points for reliability** and **30 for cost efficiency**. Cost-efficiency points require passing every hidden check. One star requires passing within budget; two and three stars require at least 80% and 97% efficiency against the stored reference cost.

Reference designs are computed offline and loaded from `data/optima.json`. To regenerate them:

```bash
python tools/optimize.py
```

The optimizer searches a finite configuration grid, screens candidates using estimated utilization, evaluates designs in cost order, and checks the winner on additional seeds. Its result is a reference within that search procedure, not a proof of the globally cheapest architecture.
