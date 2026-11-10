# System Design Simulator

Design a system, stress it, and see where it breaks. Then prove you can do it cheaply.

A discrete-event simulation (Python + SimPy) of **clients → CDN → load balancer → app replicas → cache → write queue → sharded database**, with an interactive Streamlit UI. Instead of only *talking* about a design, you run it under load and watch the bottleneck move.

> Add a demo GIF here: `![demo](docs/demo.gif)` and your live link.

## Three ways to use it

**Sandbox.** Tune every knob, add chaos events (traffic spike, replica crash, cold cache, slow database), and read findings generated from the numbers, not from an LLM.

**Challenge mode.** Each challenge gives a story, a monthly budget and a target SLO. You pick a design with a few knobs. It is graded by *hidden* chaos tests with fixed seeds (so the same design always scores the same):

| Challenge | What it teaches |
|---|---|
| Launch day: URL shortener | Horizontal scaling, CDN vs cache, surviving the loss of servers |
| Write storm: chat service | Async queues vs bigger databases, the freshness (lag) you trade for speed |
| Cache failure drill | Size the database for the miss path, not the happy path |

Score = 70 points for hidden tests passed + 30 for cost efficiency (cheapest passing design's cost / yours, only if every test passes). The reference design is found **offline** by an optimizer (`tools/optimize.py`) and stored in `data/optima.json`; the app never runs it.

**Predict-then-run.** Before a run you commit four guesses: the busiest tier, its utilization, the p95 latency bucket, and whether the design holds. They are scored against the simulator's steady state, and a running calibration score tells you whether your napkin math is improving.

## Components
CDN (edge hit rate), cache, **async write queue** (backlog, consumers, write lag, overflow rejects), **sharded database** with a hot-key control, read replicas per shard, and four load-balancing strategies. A live cost model uses illustrative prices.

## Run it
```bash
pip install -r requirements.txt
streamlit run app.py
pip install pytest && pytest          # 54 tests, including queueing-theory validation
python tools/optimize.py              # optional: regenerate data/optima.json (about 15 min on 2 cores)
```
Everything is free: Streamlit Community Cloud hosts it from a public GitHub repo, and there is no API key or database.

## How it works
| Piece | Where |
|---|---|
| Design spec, presets, cost model, napkin math | `sim/config.py` |
| SimPy engine: tiers, load balancing, cache, CDN, queue, shards, chaos events | `sim/engine.py` |
| Timelines, summary, rule-based findings | `sim/analysis.py` |
| Challenges: knobs, hidden checks, scoring | `sim/challenges.py` |
| Prediction scoring | `sim/predict.py` |
| Offline optimizer | `tools/optimize.py` |
| Erlang C / M/M/c formulas, sweeps, validation | `sim/theory.py`, `sim/experiments.py` |
| Plotly figures | `sim/charts.py` |
| UI | `app.py` |

**Modelling choices**
- Poisson arrivals and exponential service times, so a single tier is an M/M/c queue with a known answer.
- Tiers are queues in tandem (a worker is released before the next tier is called).
- Clients time out; queues are bounded and drop overflow.
- Latency percentiles count failed requests *at the timeout value*, so an overloaded system cannot look healthy by reporting only the lucky survivors.
- With the queue on, a write is acknowledged once queued; its lag is the time until the database applies it.

**Validation.** Across 30–90% utilization the simulated mean response time of a 4-server queue matches Erlang C to within about 5% on a single run (usually under 1%). The tests pool six seeds per case and assert the average is within 5%.

**How the optimizer works.** Enumerate every knob combination, drop designs whose steady-state napkin math is already above 92% on some tier, sort by cost, simulate in cost order until one passes every check, then re-verify the winner on two other seeds. "Cheapest" means cheapest in that grid under those screens, not provably cheapest in the world.

## Limitations
No network latency, retries, replica lag, or consistency model; cache invalidation is not modelled; prices and parameters are made up. It shows *where* a design breaks and roughly *when*, not production-accurate numbers. Some optimizer results depend on the toy prices (for example, a CDN can make a cache unnecessary).

## Ideas for next steps
- A guided "decide, defend, then test" mode with an LLM mentor that asks you to justify trade-offs (needs a free Groq/Gemini key).
- Save results per student for progress tracking; more challenges (rate limiting, multi-region).
