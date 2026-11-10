"""System Design Simulator: design a system, stress it, and see where it breaks.

Run locally:  streamlit run app.py
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import streamlit as st

from sim import charts
from sim.analysis import TIER_LABEL, diagnose, summarize, timeline
from sim.config import (EVENT_KINDS, LB_STRATEGIES, AppTier, CacheTier, Config, DBTier, Event, Workload,
                        app_capacity_rps, config_from_dict, presets)
from sim.engine import run
from sim.experiments import sweep_load, sweep_replicas, validate_mmc

st.set_page_config(page_title="System Design Simulator", page_icon="\U0001F9EA", layout="wide")

MAX_EV = 4
PRESETS = presets()
FIRST_PRESET = next(iter(PRESETS))

st.markdown(
    """
    <style>
      .block-container {padding-top: 2.2rem; max-width: 1250px;}
      [data-testid="stMetric"] {border: 1px solid rgba(137,135,129,.30); border-radius: 12px; padding: 12px 16px;}
      [data-testid="stMetricLabel"] {opacity: .75;}
      h1 {letter-spacing: -0.02em;}
    </style>
    """,
    unsafe_allow_html=True,
)


def current_theme() -> str:
    try:
        return "dark" if st.context.theme.type == "dark" else "light"
    except Exception:
        return "light"


THEME = current_theme()


# ------------------------------------------------------------------ session state <-> Config
def load_into_state(cfg: Config) -> None:
    ss = st.session_state
    w, a, c, d = cfg.workload, cfg.app, cfg.cache, cfg.db
    ss.w_rps, ss.w_read, ss.w_dur = int(w.rps), int(round(w.read_ratio * 100)), int(w.duration_s)
    ss.w_timeout, ss.w_seed = int(w.timeout_ms or 1000), int(cfg.seed)
    ss.a_rep, ss.a_work, ss.a_lat = int(a.replicas), int(a.workers), float(a.latency_ms)
    ss.a_lb, ss.a_maxq = a.lb_strategy, int(a.max_queue or 200)
    ss.c_en, ss.c_hit, ss.c_lat = bool(c.enabled), int(round(c.hit_rate * 100)), float(c.latency_ms)
    ss.d_work, ss.d_read, ss.d_write, ss.d_rep = int(d.workers), float(d.read_ms), float(d.write_ms), int(d.read_replicas)
    for i in range(MAX_EV):
        e = cfg.events[i] if i < len(cfg.events) else None
        ss[f"ev{i}_on"] = e is not None
        ss[f"ev{i}_kind"] = e.kind if e else "traffic_spike"
        ss[f"ev{i}_start"] = float(e.start_s) if e else 25.0
        ss[f"ev{i}_dur"] = float(e.duration_s) if e else 15.0
        ss[f"ev{i}_mag"] = float(e.magnitude) if e else EVENT_KINDS["traffic_spike"][2]
    ss.cfg_name = cfg.name


def on_preset_change() -> None:
    load_into_state(PRESETS[st.session_state.preset].cfg)
    st.session_state.committed = None
    for k in ("exp_rep", "exp_load"):
        st.session_state.pop(k, None)


def build_cfg() -> Config:
    ss = st.session_state
    events = [Event(ss[f"ev{i}_kind"], float(ss[f"ev{i}_start"]), float(ss[f"ev{i}_dur"]), float(ss[f"ev{i}_mag"]))
              for i in range(MAX_EV) if ss[f"ev{i}_on"]]
    return Config(
        name=ss.cfg_name,
        app=AppTier(ss.a_rep, ss.a_work, float(ss.a_lat), ss.a_lb, int(ss.a_maxq)),
        cache=CacheTier(bool(ss.c_en), ss.c_hit / 100.0, float(ss.c_lat), 64),
        db=DBTier(ss.d_work, float(ss.d_read), float(ss.d_write), ss.d_rep, 500),
        workload=Workload(float(ss.w_rps), ss.w_read / 100.0, float(ss.w_dur), float(ss.w_timeout), 5.0),
        events=events, seed=int(ss.w_seed),
    )


if "preset" not in st.session_state:
    st.session_state.preset = FIRST_PRESET
    load_into_state(PRESETS[FIRST_PRESET].cfg)
    st.session_state.committed = None

# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.markdown("### \U0001F9EA Design lab")
    st.selectbox("Scenario", list(PRESETS), key="preset", on_change=on_preset_change)
    run_clicked = st.button("▶  Run simulation", type="primary", width="stretch")

    with st.expander("Workload", expanded=True):
        st.slider("Requests per second", 10, 3000, step=10, key="w_rps")
        st.slider("Reads (%)", 0, 100, step=5, key="w_read")
        st.slider("Simulated duration (s)", 30, 180, step=10, key="w_dur")
        st.number_input("Client timeout (ms)", 100, 10000, step=100, key="w_timeout")
        st.number_input("Random seed", 0, 10_000, key="w_seed")
    with st.expander("App tier (horizontal scaling)", expanded=True):
        st.slider("Replicas", 1, 16, key="a_rep")
        st.slider("Workers per replica", 1, 32, key="a_work")
        st.slider("Mean service time (ms)", 1.0, 200.0, step=1.0, key="a_lat")
        st.selectbox("Load balancing", list(LB_STRATEGIES), format_func=LB_STRATEGIES.get, key="a_lb")
        st.number_input("Max queue per replica", 10, 2000, step=10, key="a_maxq")
    with st.expander("Cache"):
        st.checkbox("Use a cache", key="c_en")
        st.slider("Hit rate (%)", 0, 100, step=1, key="c_hit")
        st.slider("Lookup time (ms)", 0.5, 20.0, step=0.5, key="c_lat")
    with st.expander("Database"):
        st.slider("Connections per node", 1, 64, key="d_work")
        st.slider("Read time (ms)", 1.0, 100.0, step=1.0, key="d_read")
        st.slider("Write time (ms)", 1.0, 200.0, step=1.0, key="d_write")
        st.slider("Read replicas", 0, 6, key="d_rep")
    with st.expander("Chaos events"):
        for i in range(MAX_EV):
            st.checkbox(f"Event {i + 1}", key=f"ev{i}_on")
            if st.session_state[f"ev{i}_on"]:
                st.selectbox("Type", list(EVENT_KINDS), format_func=lambda k: EVENT_KINDS[k][0], key=f"ev{i}_kind",
                             label_visibility="collapsed")
                c1, c2, c3 = st.columns(3)
                c1.number_input("Start (s)", 0.0, 600.0, step=5.0, key=f"ev{i}_start")
                c2.number_input("Length (s)", 1.0, 300.0, step=5.0, key=f"ev{i}_dur")
                c3.number_input(EVENT_KINDS[st.session_state[f"ev{i}_kind"]][1].capitalize(), 0.0, 100.0, step=0.5,
                                key=f"ev{i}_mag")

cfg = build_cfg()
cfg_key = json.dumps(cfg.to_dict(), sort_keys=True)
if run_clicked or st.session_state.get("committed") is None:
    st.session_state.committed = cfg_key
committed = st.session_state.committed
stale = committed != cfg_key


@st.cache_data(show_spinner=False, max_entries=24)
def simulate(cfg_json: str):
    c = config_from_dict(json.loads(cfg_json))
    res = run(c)
    tl = timeline(res)
    summ = summarize(res, tl)
    return res, tl, summ, diagnose(res, summ, tl)


def plot(fig, key=None):
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False}, key=key)


def progress_cb(bar):
    return lambda frac, label: bar.progress(min(frac, 1.0), text=f"Simulating {label}")


# ------------------------------------------------------------------ header
st.title("System Design Simulator")
st.caption("Design it. Stress it. See where it breaks. A discrete-event simulation of clients → load balancer "
           "→ app replicas → cache → database, validated against queueing theory.")

tab_results, tab_exp, tab_val, tab_about = st.tabs(["Results", "Experiments", "Validation", "How it works"])

# ================================================================== results
with tab_results:
    pset = PRESETS[st.session_state.preset]
    st.info(f"**Scenario.** {pset.story}\n\n**Try this.** {pset.try_this}")
    if stale:
        st.warning("Settings changed. Press **▶ Run simulation** in the sidebar to apply them.")

    with st.spinner("Simulating..."):
        res, tl, summ, findings = simulate(committed)
    ccfg = res.cfg
    for wmsg in res.warnings:
        st.warning(wmsg)

    b = summ["bottleneck"]
    bst = summ["tiers"][b]["status"] if b else "good"
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Offered load", f"{summ['offered_rps']:,.0f} rps", help="Average over the run, after warm-up.")
    k2.metric("Served", f"{summ['served_rps']:,.0f} rps")
    k3.metric("Success rate", f"{summ['success_rate']:.1%}",
              delta=None if summ["success_rate"] >= 0.99 else f"-{1 - summ['success_rate']:.1%} failed",
              delta_color="normal")
    k4.metric("p95 latency", f"{summ['p95_ms']:,.0f} ms", help="Failed requests count as the timeout value.")
    k5.metric("Most loaded tier", TIER_LABEL[b] if b else "-", delta=charts.STATUS_TEXT[bst],
              delta_color="off", delta_arrow="off")

    st.markdown("#### Architecture")
    plot(charts.architecture_figure(ccfg, summ, THEME), key="arch")
    st.caption("Box color shows each tier's 90th-percentile utilization over the run: "
               "✓ OK below 70%, ▲ Warm 70–85%, ▲ Hot 85–95%, ✕ Saturated above 95%.")

    st.markdown("#### What the simulation found")
    ICON = {"critical": st.error, "serious": st.warning, "good": st.success, "info": st.info}
    for f in findings:
        ICON[f["level"]](f"**{f['title']}**\n\n{f['detail']}")

    st.markdown("#### Timeline")
    plot(charts.timeline_figure(res, tl, THEME), key="timeline")

    left, right = st.columns([1.25, 1])
    with left:
        st.markdown("#### Latency distribution")
        plot(charts.latency_hist_figure(res, THEME), key="hist")
    with right:
        st.markdown("#### Napkin math vs simulation")
        rows = []
        for t, st_ in summ["tiers"].items():
            exp = summ["expected"].get(t)
            rows.append({"Tier": TIER_LABEL[t],
                         "Predicted": f"{exp:.0%}" if exp is not None else "-",
                         "Sim. mean": f"{st_['mean_util']:.0%}",
                         "Sim. p90": f"{st_['p90_util']:.0%}"})
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        st.caption("Utilization. Predicted = rps × service time ÷ workers at steady load, with no chaos "
                   "events. Where it disagrees with the simulation, an event or a queueing effect is doing the damage.")

    d1, d2, _ = st.columns([1, 1, 2])
    d1.download_button("Download summary (JSON)",
                       json.dumps({"config": ccfg.to_dict(), "summary": summ, "findings": findings}, indent=2,
                                  default=float), file_name="simulation_summary.json", width="stretch")
    d2.download_button("Download timeline (CSV)", tl.round(4).to_csv(), file_name="timeline.csv", width="stretch")

# ================================================================== experiments
with tab_exp:
    base = config_from_dict(json.loads(committed))
    st.markdown("Experiments run on the **current design with chaos events removed**, so they measure steady "
                "state. Each point is its own short simulation.")

    st.markdown("### Scaling lab: do more replicas help, and does the load balancer matter?")
    c1, c2, c3 = st.columns([1.4, 1.4, 1])
    strats = c1.multiselect("Strategies to compare", list(LB_STRATEGIES), default=["least_queue", "random", "shared"],
                            format_func=LB_STRATEGIES.get)
    lo, hi = c2.slider("Replica range", 1, 12, (1, 8))
    go_rep = c3.button("Run scaling experiment", width="stretch")
    values = sorted({int(round(v)) for v in np.linspace(lo, hi, min(hi - lo + 1, 7))})
    st.caption(f"{len(values) * max(len(strats), 1)} short simulations at {base.workload.rps:,.0f} rps.")
    if go_rep and strats:
        bar = st.progress(0.0, text="Simulating...")
        df = sweep_replicas(base, values, strats, duration_s=20, warmup_s=4, progress=progress_cb(bar))
        bar.empty()
        st.session_state.exp_rep = (committed, df)
    if "exp_rep" in st.session_state:
        key, df = st.session_state.exp_rep
        if key != committed:
            st.warning("Showing an earlier design. Re-run to update.")
        plot(charts.replica_sweep_figure(df, base, THEME), key="rep_fig")
        ok = df[df.success_rate >= 0.99]
        if len(ok):
            first = ok.groupby("strategy").replicas.min()
            st.markdown("**Fewest replicas that serve at least 99% of requests:** " +
                        ", ".join(f"{charts.STRATEGY_NAME.get(k, k)} **{v}**" for k, v in first.items()) + ".")
        else:
            st.markdown("**No configuration in this range reached 99% success.** Widen the range or check other tiers.")
        st.caption("Look for where throughput stops growing with replicas: that is the next bottleneck, "
                   "which horizontal scaling of the app tier cannot fix. Strategies only diverge when replicas "
                   "run at roughly 80–90% utilization; try the **Lab: load balancing strategy** scenario.")

    st.divider()
    st.markdown("### Load test: find the knee")
    c1, c2 = st.columns([2.8, 1])
    mult = c1.slider("Test up to (× current load)", 1.0, 4.0, 2.0, 0.25)
    go_load = c2.button("Run load test", width="stretch")
    if go_load:
        bar = st.progress(0.0, text="Simulating...")
        vals = np.linspace(base.workload.rps * 0.2, base.workload.rps * mult, 9)
        df = sweep_load(base, vals, duration_s=25, warmup_s=5, progress=progress_cb(bar))
        bar.empty()
        st.session_state.exp_load = (committed, df)
    if "exp_load" in st.session_state:
        key, df = st.session_state.exp_load
        if key != committed:
            st.warning("Showing an earlier design. Re-run to update.")
        plot(charts.load_sweep_figure(df, base, THEME), key="load_fig")
        base_p95 = float(df.p95_ms.iloc[0])
        bad = df[(df.success_rate < 0.99) | (df.p95_ms > max(3 * base_p95, base_p95 + 100))]
        if len(bad):
            st.markdown(f"**The knee is near {float(bad.target_rps.iloc[0]):,.0f} rps.** Beyond it, queues build, "
                        f"latency jumps, and throughput flattens or falls. App tier nominal capacity: "
                        f"{app_capacity_rps(base):,.0f} rps.")
        else:
            st.markdown("**No knee in this range.** The design absorbed everything tested. Push the multiplier higher.")

# ================================================================== validation
with tab_val:
    st.markdown("### Is the simulator telling the truth?")
    st.markdown("A single tier with Poisson arrivals and exponential service is an **M/M/c queue**, which has an exact "
                "answer (the Erlang C formula). If the simulator matches it across loads, its queueing behavior can "
                "be trusted. The automated tests in `tests/` assert this on every change.")
    c1, c2, c3 = st.columns([1, 1, 1])
    vc = c1.slider("Servers (c)", 1, 16, 4)
    vmu = c2.slider("Service rate per server (rps)", 10, 200, 50, 10)
    go_val = c3.button("Run validation", width="stretch")
    if go_val:
        bar = st.progress(0.0, text="Simulating...")
        rhos = (0.3, 0.5, 0.7, 0.8, 0.9)
        st.session_state.val = (vc, vmu, validate_mmc(vc, float(vmu), rhos, progress=progress_cb(bar)))
        bar.empty()
    if "val" in st.session_state:
        vc_, vmu_, vdf = st.session_state.val
        plot(charts.validation_figure(vdf, THEME), key="val_fig")
        show = vdf.assign(utilization=(vdf.utilization * 100).round(0).astype(int).astype(str) + "%").round(2)
        show.columns = ["Utilization", "Arrivals (rps)", "Simulated (ms)", "Theory (ms)", "Error (%)", "Requests"]
        st.dataframe(show, hide_index=True, width="stretch")
        worst = float(vdf.error_pct.abs().max())
        st.markdown(f"**Worst error: {worst:.1f}%** for c={vc_}, μ={vmu_} rps. A single run is a noisy estimate "
                    f"(consecutive delays are correlated, so the sample mean wanders), which is why the test suite "
                    f"pools six seeds per case and checks the average for bias.")

# ================================================================== about
with tab_about:
    st.markdown(
        """
### Model
- **Arrivals** are Poisson with a time-varying rate (for traffic spikes). **Service times** are exponential.
- **Tiers** are queues in tandem: client → load balancer → app replicas → cache → database.
  A worker is released before the next tier is called (like an async server).
- **Load balancing**: least-queue, round robin, random, or one shared queue (the ideal M/M/c pooling case).
- **Cache**: each read hits with probability *hit rate*; misses go to the database. Writes skip the cache.
- **Database**: one primary (writes, and reads if there are no replicas) plus optional read replicas.
- **Clients give up** after the timeout; queues are bounded and drop overflow.
- **Latency percentiles count failures at the timeout value**, so an overloaded system can't look healthy by
  reporting only its lucky survivors.

### Chaos events
Traffic spikes, app replica crashes, a cold cache (hit rate drops, then recovers over 15 s), and a slow database.

### Limits (stated honestly)
- No network latency, no retries, no replication lag, no consistency model, and requests in a tier are independent.
- Cache invalidation on writes is not modeled.
- Fixed parameters: it shows *where* a design breaks and roughly *when*, not production-accurate numbers.

### Extending it
Add a tier in `sim/engine.py` (a `Tier` plus a step in `_request`), a chart in `sim/charts.py`, and a validation
test in `tests/`.
        """
    )
