# System Design Simulator

Design a system, stress it, and see where it breaks.

A discrete-event simulation (Python + SimPy) of **clients → load balancer → app replicas → cache → database**,
with an interactive Streamlit UI. Instead of only *talking* about a design, you run it under load and watch the
bottleneck move.

> Add a demo GIF here: `![demo](docs/demo.gif)` and your live link.

## What it does

- **Scenarios** that tell a story: a traffic spike on a URL shortener, a write-heavy chat service, a cache that
  goes cold, replicas that crash, and a load-balancing lab.
- **Chaos events**: traffic spike, replica crash, cold cache (recovers over 15 s), slow database.
- **Diagram colored by health**: every tier is OK / Warm / Hot / Saturated (icon + label, never color alone).
- **Findings** generated from the numbers, not from an LLM: saturated tier, replicas needed, why read replicas
  don't fix a write bottleneck, how much load jumped on the database when the cache went cold.
- **Napkin math vs simulation**: predict utilization first, then see where you were wrong.
- **Experiments**: replica count × load-balancing strategy sweep, and a load test that finds the latency "knee".
- **Validation**: simulated M/M/c response times against the closed-form Erlang C result.

## Run it

```bash
pip install -r requirements.txt
streamlit run app.py
pip install pytest && pytest        # 28 tests, including queueing-theory validation
```

Everything is free: Streamlit Community Cloud hosts it from a public GitHub repo, and there is no API key or
database.

## How it works

| Piece | Where |
|---|---|
| Design spec (dataclasses), presets, napkin math | `sim/config.py` |
| SimPy engine: tiers, load balancing, cache, chaos events | `sim/engine.py` |
| Timelines, summary, rule-based findings | `sim/analysis.py` |
| Erlang C / M/M/c formulas | `sim/theory.py` |
| Sweeps and validation | `sim/experiments.py` |
| Plotly figures | `sim/charts.py` |
| UI | `app.py` |

**Modelling choices**

- Poisson arrivals and exponential service times, so a single tier is an M/M/c queue with a known answer.
- Tiers are queues in tandem (a worker is released before the next tier is called).
- Clients time out; queues are bounded and drop overflow.
- Latency percentiles count failed requests *at the timeout value*, so an overloaded system cannot look healthy
  by reporting only the lucky survivors.

**Validation.** Across 30–90% utilization the simulated mean response time of a 4-server queue matches Erlang C
to within about 5% on a single run (usually under 1%). The test suite pools six seeds per case and asserts
the average is within 5%.

## Limitations

No network latency, retries, replication lag, or consistency model; cache invalidation on writes is not modelled;
parameters are fixed. It shows *where* a design breaks and roughly *when*, not production-accurate numbers.

## Ideas for next steps

- A queue tier (async writes) and a sharded database.
- A guided "decide, defend, then test" mode: the student picks parameters and justifies trade-offs, then the
  simulator checks the choice.
- Save results per student for progress tracking.
