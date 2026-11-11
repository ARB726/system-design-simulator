"""System Design Simulator: design a system, stress it, and see where it breaks.

Two modes:
  * Sandbox   - tune everything, run chaos scenarios, read the findings.
  * Challenge - meet hidden SLO tests at the lowest cost; graded against an offline optimizer.
Either mode can be played "predict first": commit your napkin math, then see how close it was.

Run locally:  streamlit run app.py
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import streamlit as st

from sim import charts
from sim import progress as pg
from sim.analysis import TIER_LABEL, diagnose, summarize, timeline
from sim.challenges import (KNOB_HELP, KNOB_LABELS, apply_design, challenges, default_design, design_cost,
                            load_optima, run_check, score_design)
from sim.config import (EVENT_KINDS, LB_STRATEGIES, AppTier, CacheTier, CDNTier, Config, DBTier, Event, QueueTier,
                        Workload, app_capacity_rps, config_from_dict, cost_breakdown, expected_utilization,
                        monthly_cost, presets)
from sim.engine import run
from sim.experiments import sweep_load, sweep_replicas, validate_mmc
from sim.predict import BUCKETS, POINTS, Prediction, score_prediction
from sim.sharecard import design_lines, make_card
from sim.themes import (DEFAULT_THEME, INDUSTRIES, INDUSTRY_EMOJI, PRESET_INDUSTRY, THEMES, accent, tag, theme_css)

st.set_page_config(page_title="System Design Simulator", page_icon=":material/hub:", layout="wide")

MAX_EV = 4
PRESETS = presets()
FIRST_PRESET = next(iter(PRESETS))
CHALLENGES = challenges()
OPTIMA = load_optima()
FIRST_CHALLENGE = next(iter(CHALLENGES))
ORDER = list(CHALLENGES)          # campaign order

def current_theme() -> str:
    try:
        return "dark" if st.context.theme.type == "dark" else "light"
    except Exception:
        return "light"


THEME = current_theme()
ss = st.session_state
if "progress" not in ss:
    ss.progress = pg.empty()
ss.setdefault("theme", DEFAULT_THEME)
ss.setdefault("industry", "All")

SANDBOX_KEYS = (["preset", "theme", "industry", "progress", "predict_on", "cfg_name", "w_rps", "w_read", "w_dur", "w_timeout", "w_seed", "a_rep", "a_work",
                 "a_lat", "a_lb", "a_maxq", "c_en", "c_hit", "c_lat", "x_en", "x_hit", "x_lat", "q_en", "q_cons",
                 "q_depth", "d_work", "d_read", "d_write", "d_rep", "d_shards", "d_hot"] +
                [f"ev{i}_{s}" for i in range(MAX_EV) for s in ("on", "kind", "start", "dur", "mag")])
# Streamlit drops widget state for widgets that are not drawn; re-assigning keeps it across mode switches.
for _k in SANDBOX_KEYS + [f"k_{k}" for k in KNOB_LABELS] + ["chal"]:
    if _k in ss:
        ss[_k] = ss[_k]


# ------------------------------------------------------------------ session state <-> Config
def load_into_state(cfg: Config) -> None:
    w, a, c, x, q, d = cfg.workload, cfg.app, cfg.cache, cfg.cdn, cfg.queue, cfg.db
    ss.w_rps, ss.w_read, ss.w_dur = int(w.rps), int(round(w.read_ratio * 100)), int(w.duration_s)
    ss.w_timeout, ss.w_seed = int(w.timeout_ms or 1000), int(cfg.seed)
    ss.a_rep, ss.a_work, ss.a_lat = int(a.replicas), int(a.workers), float(a.latency_ms)
    ss.a_lb, ss.a_maxq = a.lb_strategy, int(a.max_queue or 200)
    ss.c_en, ss.c_hit, ss.c_lat = bool(c.enabled), int(round(c.hit_rate * 100)), float(c.latency_ms)
    ss.x_en, ss.x_hit, ss.x_lat = bool(x.enabled), int(round(x.hit_rate * 100)), float(x.latency_ms)
    ss.q_en, ss.q_cons, ss.q_depth = bool(q.enabled), int(q.consumers), int(q.max_depth)
    ss.d_work, ss.d_read, ss.d_write, ss.d_rep = int(d.workers), float(d.read_ms), float(d.write_ms), int(d.read_replicas)
    ss.d_shards, ss.d_hot = int(d.shards), int(round(d.hot_share * 100))
    for i in range(MAX_EV):
        e = cfg.events[i] if i < len(cfg.events) else None
        ss[f"ev{i}_on"] = e is not None
        ss[f"ev{i}_kind"] = e.kind if e else "traffic_spike"
        ss[f"ev{i}_start"] = float(e.start_s) if e else 25.0
        ss[f"ev{i}_dur"] = float(e.duration_s) if e else 15.0
        ss[f"ev{i}_mag"] = float(e.magnitude) if e else EVENT_KINDS["traffic_spike"][2]
    ss.cfg_name = cfg.name


def on_preset_change() -> None:
    load_into_state(PRESETS[ss.preset].cfg)
    ss.committed = None
    ss.pred_for = None
    for k in ("exp_rep", "exp_load"):
        ss.pop(k, None)


def build_cfg() -> Config:
    events = [Event(ss[f"ev{i}_kind"], float(ss[f"ev{i}_start"]), float(ss[f"ev{i}_dur"]), float(ss[f"ev{i}_mag"]))
              for i in range(MAX_EV) if ss[f"ev{i}_on"]]
    return Config(
        name=ss.cfg_name,
        app=AppTier(ss.a_rep, ss.a_work, float(ss.a_lat), ss.a_lb, int(ss.a_maxq)),
        cache=CacheTier(bool(ss.c_en), ss.c_hit / 100.0, float(ss.c_lat), 64),
        cdn=CDNTier(bool(ss.x_en), ss.x_hit / 100.0, float(ss.x_lat)),
        queue=QueueTier(bool(ss.q_en), int(ss.q_cons), int(ss.q_depth), 2.0),
        db=DBTier(ss.d_work, float(ss.d_read), float(ss.d_write), ss.d_rep, 500, int(ss.d_shards),
                  ss.d_hot / 100.0 if ss.d_shards > 1 else 0.0),
        workload=Workload(float(ss.w_rps), ss.w_read / 100.0, float(ss.w_dur), float(ss.w_timeout), 5.0),
        events=events, seed=int(ss.w_seed),
    )


def load_challenge(cid: str) -> None:
    d = default_design(CHALLENGES[cid])
    for k in KNOB_LABELS:
        ss[f"k_{k}"] = d[k]


def pick_challenge(cid: str) -> None:
    if ss.get("industry", "All") not in ("All", CHALLENGES[cid].industry):
        ss.industry = "All"
    ss.chal = cid
    load_challenge(cid)
    ss.chal_last = None


def on_challenge_change() -> None:
    load_challenge(ss.chal)
    ss.chal_last = None


def current_design(cid: str) -> dict:
    ch = CHALLENGES[cid]
    d = default_design(ch)
    for k in KNOB_LABELS:
        if f"k_{k}" in ss:
            d[k] = ss[f"k_{k}"]
    return d


# ------------------------------------------------------------------ cached simulation
@st.cache_data(show_spinner=False, max_entries=24)
def simulate(cfg_json: str):
    c = config_from_dict(json.loads(cfg_json))
    res = run(c)
    tl = timeline(res)
    summ = summarize(res, tl)
    return res, tl, summ, diagnose(res, summ, tl)


@st.cache_data(show_spinner=False, max_entries=48)
def grade(cid: str, design_json: str):
    """Run every hidden check. Returns per-check results and the steady-state summary (the prediction baseline)."""
    ch, design = CHALLENGES[cid], json.loads(design_json)
    out, base = [], None
    for i, chk in enumerate(ch.checks):
        r = run_check(ch, design, chk, keep_result=(i == 0))
        if i == 0:
            base = r.pop("summary")
            r.pop("res")
            r.pop("tl")
        out.append(r)
    return out, base


@st.cache_data(show_spinner=False, max_entries=12)
def replay(cid: str, design_json: str, idx: int):
    from sim.challenges import check_config
    ch, design = CHALLENGES[cid], json.loads(design_json)
    cfg = check_config(ch, design, ch.checks[idx])
    res = run(cfg)
    tl = timeline(res)
    summ = summarize(res, tl)
    return res, tl, summ, diagnose(res, summ, tl)


def plot(fig, key=None):
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False}, key=key)


def progress_cb(bar):
    return lambda frac, label: bar.progress(min(frac, 1.0), text=f"Simulating {label}")


LEVEL = {"critical": st.error, "serious": st.warning, "good": st.success, "info": st.info}


def show_findings(findings):
    for f in findings:
        LEVEL[f["level"]](f"**{f['title']}**\n\n{f['detail']}")


# ------------------------------------------------------------------ predict-then-run widgets
def prediction_form(cfg: Config, form_key: str, holds_label: str, allow_skip: bool):
    """Returns (submitted, Prediction | None)."""
    tiers = list(expected_utilization(cfg))
    with st.form(form_key):
        st.subheader("Predict before you run", icon=":material/psychology:")
        st.caption("Do the napkin math first. Points are awarded for matching the simulator; "
                   f"{POINTS['bottleneck']} bottleneck, {POINTS['util']} utilization, {POINTS['p95']} latency, "
                   f"{POINTS['holds']} verdict.")
        c1, c2 = st.columns(2)
        b = c1.selectbox("Which tier is the busiest in steady traffic?", tiers, format_func=lambda t: TIER_LABEL[t])
        u = c2.slider("How busy is that tier? (% of workers)", 0, 150, 50, 5)
        p = c1.radio("Where will steady-state p95 latency land?", BUCKETS, index=1)
        h = c2.radio(holds_label, ["Yes", "No"], index=0, horizontal=True)
        skip = st.checkbox("Skip the prediction", value=False) if allow_skip else False
        go = st.form_submit_button("Lock prediction and run", icon=":material/play_arrow:", type="primary", width="stretch")
    if not go:
        return False, None
    if skip:
        return True, None
    return True, Prediction(b, u / 100.0, BUCKETS.index(p), h == "Yes")


def record_calibration(score: dict) -> None:
    ss.setdefault("calib", []).append(score["total"])


def show_prediction_score(ps: dict) -> None:
    st.markdown("#### Napkin math vs the simulator")
    cols = st.columns(5)
    cols[0].metric("Calibration", f"{ps['total']:.0f} / {ps['max_points']}")
    labels = dict(bottleneck="Bottleneck", util="Utilization", p95="Latency bucket", holds="Verdict")
    for col, (k, v) in zip(cols[1:], ps["parts"].items()):
        col.metric(labels[k], f"{v:g} / {POINTS[k]}")
    t = ps["truth"]
    st.caption(f"Actual steady state (no chaos): busiest tier {TIER_LABEL.get(t['bottleneck'], '-')} at "
               f"{t['utilization']:.0%}, p95 {t['p95_ms']:.0f} ms (bucket '{BUCKETS[t['p95_bucket']]}').")
    for n in ps["notes"]:
        st.info(n)
    cal = ss.get("calib", [])
    if len(cal) > 1:
        st.caption(f"Your running calibration: average {np.mean(cal):.0f} over {len(cal)} predictions.")


# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.subheader("Design lab", icon=":material/hub:")
    st.caption("Build intuition. Test your architecture.")
    st.selectbox("Theme", list(THEMES), format_func=lambda n: f"{THEMES[n]['emoji']}  {n}", key="theme")
    st.markdown(theme_css(ss.theme, THEME == "dark"), unsafe_allow_html=True)
    charts.ACCENT = accent(ss.theme, THEME == "dark")

    prog = ss.progress
    xp = pg.xp_total(prog)
    info = pg.level_info(xp)
    st.markdown(f"**Level {info['level']} · {info['title']}**")
    st.progress(info["frac"], text=f"{xp} XP" + (f" · {info['to_next']} to {info['next_title']}" if info["next_title"] else " · max level"))
    with st.expander("Badges and progress"):
        st.markdown("".join(f'<span class="badge{"" if b in prog["badges"] else " off"}" title="{d}">{n}</span>'
                            for b, (n, d) in pg.BADGES.items()), unsafe_allow_html=True)
        st.caption(f"{len(prog['badges'])} of {len(pg.BADGES)} earned. Hover a badge to see how to earn it.")
        st.download_button("Save progress (JSON)", pg.dumps(prog), file_name="sysdesign_progress.json", width="stretch")
        up = st.file_uploader("Load progress", type="json", label_visibility="collapsed")
        if up is not None and ss.get("_loaded_upload") != (up.name, up.size):
            try:
                ss.progress = pg.loads(up.getvalue().decode("utf-8", "replace"), ORDER)
                ss._loaded_upload = (up.name, up.size)
                st.rerun()
            except ValueError as e:
                st.error(str(e))

    st.radio("Mode", ["Sandbox", "Challenge"], horizontal=True, key="mode", label_visibility="collapsed")
    MODE = ss.mode
    st.selectbox("Industry", INDUSTRIES, format_func=lambda i: f"{INDUSTRY_EMOJI.get(i, '')}  {i}".strip(), key="industry")

    if MODE == "Sandbox":
        if "preset" not in ss or "w_rps" not in ss:
            ss.preset = ss.get("preset") if ss.get("preset") in PRESETS else FIRST_PRESET
            load_into_state(PRESETS[ss.preset].cfg)
            ss.committed = None
        p_opts = [n for n in PRESETS if ss.industry == "All" or PRESET_INDUSTRY.get(n) == ss.industry] or list(PRESETS)
        if ss.preset not in p_opts:
            ss.preset = p_opts[0]
            on_preset_change()
        st.selectbox("Scenario", p_opts, key="preset", on_change=on_preset_change)
        st.toggle("Predict before running", key="predict_on",
                  help="Commit your napkin math first, then see how close it was.")
        run_clicked = False
        if ss.get("predict_on"):
            st.caption("Predict mode: use the form on the Results tab to run.")
        else:
            run_clicked = st.button("Run simulation", icon=":material/play_arrow:", type="primary", width="stretch")

        with st.expander("Workload", expanded=True):
            st.slider("Requests per second", 10, 3000, step=10, key="w_rps")
            st.slider("Reads (%)", 0, 100, step=5, key="w_read")
            st.slider("Simulated duration (s)", 30, 180, step=10, key="w_dur")
            st.number_input("Client timeout (ms)", 100, 10000, step=100, key="w_timeout")
            st.number_input("Random seed", 0, 10_000, key="w_seed")
        with st.expander("CDN"):
            st.checkbox("Use a CDN", key="x_en", help="Answers a share of reads at the edge.")
            st.slider("Reads served at the edge (%)", 0, 95, step=5, key="x_hit")
            st.slider("Edge latency (ms)", 1.0, 50.0, step=1.0, key="x_lat")
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
        with st.expander("Write queue (async writes)"):
            st.checkbox("Queue writes", key="q_en", help="Acknowledge a write once it is queued; apply it later.")
            st.slider("Consumers", 1, 64, key="q_cons")
            st.number_input("Max backlog", 100, 50000, step=500, key="q_depth")
        with st.expander("Database"):
            st.slider("Connections per node", 1, 64, key="d_work")
            st.slider("Read time (ms)", 1.0, 100.0, step=1.0, key="d_read")
            st.slider("Write time (ms)", 1.0, 200.0, step=1.0, key="d_write")
            st.slider("Read replicas (per shard)", 0, 6, key="d_rep")
            st.slider("Shards", 1, 8, key="d_shards")
            if ss.d_shards > 1:
                st.slider("Traffic on the hottest shard (%)", 0, 95, step=5, key="d_hot",
                          help="0 = perfectly even. A hot key sends far more than 1/N of the traffic to one shard.")
        with st.expander("Chaos events"):
            for i in range(MAX_EV):
                st.checkbox(f"Event {i + 1}", key=f"ev{i}_on")
                if ss[f"ev{i}_on"]:
                    st.selectbox("Type", list(EVENT_KINDS), format_func=lambda k: EVENT_KINDS[k][0], key=f"ev{i}_kind",
                                 label_visibility="collapsed")
                    c1, c2, c3 = st.columns(3)
                    c1.number_input("Start (s)", 0.0, 600.0, step=5.0, key=f"ev{i}_start")
                    c2.number_input("Length (s)", 1.0, 300.0, step=5.0, key=f"ev{i}_dur")
                    c3.number_input(EVENT_KINDS[ss[f"ev{i}_kind"]][1].capitalize(), 0.0, 100.0, step=0.5, key=f"ev{i}_mag")
        cfg = build_cfg()
        st.caption(f"Estimated cost **${monthly_cost(cfg):,.0f}/month** (illustrative prices).")

    else:  # ------------------------------------------------------------ challenge controls
        if "chal" not in ss or f"k_{next(iter(KNOB_LABELS))}" not in ss:
            ss.chal = ss.get("chal") if ss.get("chal") in CHALLENGES else FIRST_CHALLENGE
            load_challenge(ss.chal)
        open_ids = pg.unlocked(ss.progress, ORDER)
        c_opts = [k for k in open_ids if ss.industry == "All" or CHALLENGES[k].industry == ss.industry] or open_ids
        if ss.chal not in c_opts:
            pick_challenge(c_opts[0])
        star_lbl = {k: f"{'★' * ss.progress['stars'].get(k, 0)}{'☆' * (3 - ss.progress['stars'].get(k, 0))}  {CHALLENGES[k].title}"
                    for k in ORDER}
        st.selectbox("Challenge", c_opts, format_func=lambda k: star_lbl.get(k, k), key="chal",
                     on_change=on_challenge_change)
        CH = CHALLENGES[ss.chal]
        st.caption("Choose a design. It is graded by hidden tests.")
        locked = []
        for k, label in KNOB_LABELS.items():
            vals = CH.knobs.get(k)
            if vals is None or len(vals) < 2:
                locked.append(label)
                continue
            if k == "consumers" and not ss.get("k_queue"):
                continue
            if set(vals) == {True, False}:
                st.toggle(label, key=f"k_{k}", help=KNOB_HELP[k])
            else:
                st.select_slider(label, options=vals, key=f"k_{k}", help=KNOB_HELP[k])
        if locked:
            st.caption("Fixed in this challenge: " + ", ".join(locked) + ".")
        design = current_design(ss.chal)
        cost = design_cost(CH, design)
        st.progress(min(cost / CH.budget, 1.0), text=f"Cost ${cost:,.0f} of ${CH.budget:,.0f} / month")
        if cost > CH.budget:
            st.error("Over budget. Reduce the design before grading.")

# ================================================================== header
with st.container(horizontal=True):
    st.badge("SYSTEMS LAB", icon=":material/hub:", color="blue")
    st.badge(MODE, icon=":material/science:" if MODE == "Sandbox" else ":material/flag:", color="gray")
st.title("System design simulator")
st.markdown("Design it. Stress it. **See where it breaks.**")
st.caption("Explore the tradeoffs between throughput, latency, and cost. "
           "Tune your architecture in the sidebar, then put it under pressure.")


# ================================================================== results renderer
def render_results(res, tl, summ, findings, key_prefix: str, show_cost: bool = True):
    ccfg = res.cfg
    for wmsg in res.warnings:
        st.warning(wmsg)
    b = summ["bottleneck"]
    bst = summ["tiers"][b]["status"] if b else "good"
    st.subheader("Performance overview", icon=":material/monitoring:")
    metric_row = st.container(horizontal=True)
    cols = [metric_row.container(border=True, width=180) for _ in range(6 if show_cost else 5)]
    cols[0].metric("Offered load", f"{summ['offered_rps']:,.0f} rps", help="Average over the run, after warm-up.")
    cols[1].metric("Served", f"{summ['served_rps']:,.0f} rps")
    cols[2].metric("Success rate", f"{summ['success_rate']:.1%}",
                   delta=None if summ["success_rate"] >= 0.99 else f"-{1 - summ['success_rate']:.1%} failed",
                   delta_color="normal")
    cols[3].metric("p95 latency", f"{summ['p95_ms']:,.0f} ms", help="Failed requests count as the timeout value.")
    cols[4].metric("Most loaded tier", TIER_LABEL[b] if b else "-", delta=charts.STATUS_TEXT[bst],
                   delta_color="off", delta_arrow="off")
    if show_cost:
        cols[5].metric("Est. cost", f"${monthly_cost(ccfg):,.0f}/mo", help="Illustrative prices; see How it works.")

    with st.container(border=True):
        st.subheader("Architecture", icon=":material/account_tree:")
        st.caption("Follow the request path. Each tier is colored by its 90th-percentile utilization.")
        plot(charts.architecture_figure(ccfg, summ, THEME), key=f"{key_prefix}_arch")
        st.caption("OK <70% / Warm 70-85% / Hot 85-95% / Saturated >95%")

    st.markdown("#### Live replay")
    plot(charts.replay_figure(res, tl, THEME), key=f"{key_prefix}_replay")
    st.caption("Press ▶ Play (or drag the slider). Bars change color as each tier heats up; the right panel shows queues filling.")

    st.markdown("#### What the simulation found")
    show_findings(findings)

    st.markdown("#### Timeline")
    plot(charts.timeline_figure(res, tl, THEME), key=f"{key_prefix}_timeline")

    left, right = st.columns([1.25, 1])
    with left:
        st.markdown("#### Latency distribution")
        plot(charts.latency_hist_figure(res, THEME), key=f"{key_prefix}_hist")
    with right:
        st.markdown("#### Napkin math vs simulation")
        rows = []
        for t, st_ in summ["tiers"].items():
            exp = summ["expected"].get(t)
            rows.append({"Tier": TIER_LABEL[t], "Predicted": f"{exp:.0%}" if exp is not None else "-",
                         "Sim. mean": f"{st_['mean_util']:.0%}", "Sim. p90": f"{st_['p90_util']:.0%}"})
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        st.caption("Utilization. Predicted = rps × service time ÷ workers at steady load, with no chaos "
                   "events. Where it disagrees with the simulation, an event or a queueing effect is doing the damage.")
        if show_cost:
            with st.expander("Cost breakdown"):
                bd = cost_breakdown(ccfg)
                st.dataframe(pd.DataFrame({"Component": list(bd), "$/month": [f"${v:,.0f}" for v in bd.values()]}),
                             hide_index=True, width="stretch")
    return ccfg


# ================================================================== SANDBOX
if MODE == "Sandbox":
    cfg_key = json.dumps(cfg.to_dict(), sort_keys=True)
    if run_clicked or ss.get("committed") is None:
        ss.committed = cfg_key
    committed = ss.committed
    stale = committed != cfg_key
    predict_on = bool(ss.get("predict_on"))

    tab_results, tab_exp, tab_val, tab_about = st.tabs(["Results", "Experiments", "Validation", "How it works"])

    with tab_results:
        pset = PRESETS[ss.preset]
        with st.container(border=True):
            st.badge(tag(PRESET_INDUSTRY.get(ss.preset, "")), color="blue")
            st.subheader(ss.preset.split(": ", 1)[-1])
            st.markdown(pset.story)
            st.caption(f":material/lightbulb: Try this: {pset.try_this}")

        gate = predict_on and ss.get("pred_for") != cfg_key
        if predict_on and not gate:
            committed, stale = cfg_key, False
        if gate:
            st.markdown("#### Architecture (before running)")
            plot(charts.architecture_figure(cfg, None, THEME), key="sb_blueprint")
            submitted, pred = prediction_form(cfg, "sb_predict", "Will the design hold under the whole scenario "
                                              "(at least 99% of requests succeed)?", allow_skip=True)
            if submitted:
                res, tl, summ, findings = simulate(cfg_key)
                ss.committed = cfg_key
                ss.pred_for = cfg_key
                ss.pred_score = None
                if pred is not None:
                    base_cfg = config_from_dict(json.loads(cfg_key))
                    base_cfg.events = []
                    base_summ = simulate(json.dumps(base_cfg.to_dict(), sort_keys=True))[2]
                    ss.pred_score = score_prediction(pred, base_summ, summ["success_rate"] >= 0.99)
                    record_calibration(ss.pred_score)
                    ss.pred_ev = pg.record_prediction(ss.progress, ss.pred_score, ORDER)
                st.rerun()
        else:
            if stale:
                st.warning("Settings changed. Press **Run simulation** in the sidebar to apply them.")
            with st.spinner("Simulating..."):
                res, tl, summ, findings = simulate(committed)
            pev = ss.pop("pred_ev", None)
            if pev:
                for b in pev["new_badges"]:
                    st.toast(f"Badge earned: {pg.BADGES[b][0]}", icon="\U0001F3C5")
                if pev["level_up"]:
                    st.balloons()
                    st.toast(f"Level up! {pev['level']['title']}", icon="\u2B06\uFE0F")
            if predict_on and ss.get("pred_score"):
                if pev:
                    st.success(f"+{pev['xp_gained']} XP for your prediction.")
                show_prediction_score(ss.pred_score)
                st.divider()
            ccfg = render_results(res, tl, summ, findings, "sb")

            d1, d2, _ = st.columns([1, 1, 2])
            d1.download_button("Download summary (JSON)",
                               json.dumps({"config": ccfg.to_dict(), "summary": summ, "findings": findings}, indent=2,
                                          default=float), file_name="simulation_summary.json", width="stretch")
            d2.download_button("Download timeline (CSV)", tl.round(4).to_csv(), file_name="timeline.csv", width="stretch")

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
            ss.exp_rep = (committed, df)
        if "exp_rep" in ss:
            key, df = ss.exp_rep
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
            ss.exp_load = (committed, df)
        if "exp_load" in ss:
            key, df = ss.exp_load
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
            ss.val = (vc, vmu, validate_mmc(vc, float(vmu), rhos, progress=progress_cb(bar)))
            bar.empty()
        if "val" in ss:
            vc_, vmu_, vdf = ss.val
            plot(charts.validation_figure(vdf, THEME), key="val_fig")
            show = vdf.assign(utilization=(vdf.utilization * 100).round(0).astype(int).astype(str) + "%").round(2)
            show.columns = ["Utilization", "Arrivals (rps)", "Simulated (ms)", "Theory (ms)", "Error (%)", "Requests"]
            st.dataframe(show, hide_index=True, width="stretch")
            worst = float(vdf.error_pct.abs().max())
            st.markdown(f"**Worst error: {worst:.1f}%** for c={vc_}, μ={vmu_} rps. A single run is a noisy estimate "
                        f"(consecutive delays are correlated, so the sample mean wanders), which is why the test suite "
                        f"pools six seeds per case and checks the average for bias.")
    tab_about_ = tab_about

# ================================================================== CHALLENGE
else:
    tab_chal, tab_about = st.tabs(["Challenge", "How it works"])
    CH = CHALLENGES[ss.chal]
    design = current_design(ss.chal)
    dj = json.dumps(design, sort_keys=True)
    dcfg = apply_design(CH.base, design)
    cost = design_cost(CH, design)
    opt = OPTIMA.get(CH.id) or {}
    opt_cost = opt.get("optimum_cost")

    with tab_chal:
        # ---- campaign map
        stars_total = sum(ss.progress["stars"].get(c, 0) for c in ORDER)
        st.markdown("### Campaign")
        st.progress(stars_total / (3 * len(ORDER)), text=f"{stars_total} of {3 * len(ORDER)} stars. "
                    "Earn one star on a challenge to unlock the next.")
        open_ids = pg.unlocked(ss.progress, ORDER)
        for r0 in range(0, len(ORDER), 3):
            for col, cid in zip(st.columns(3), ORDER[r0:r0 + 3]):
                c = CHALLENGES[cid]
                n = ss.progress["stars"].get(cid, 0)
                lock = cid not in open_ids
                best = ss.progress["best"].get(cid)
                if lock:
                    meta = "Locked: earn a star on the previous challenge"
                elif best is not None:
                    meta = f"Budget ${c.budget:,.0f} · best {best:.0f}/100"
                else:
                    meta = f"Budget ${c.budget:,.0f} · not played yet"
                with col.container(border=True):
                    st.badge(tag(c.industry), color="gray" if lock else "blue")
                    st.markdown(f"**{c.title}**")
                    st.markdown("\u2605" * n + "\u2606" * (3 - n))
                    st.caption(meta)
                    st.button("Playing" if cid == CH.id else "Locked" if lock else "Play challenge",
                              key=f"play_{cid}", disabled=lock or cid == CH.id,
                              icon=":material/lock:" if lock else ":material/arrow_forward:",
                              on_click=pick_challenge, args=(cid,), width="stretch")
        st.divider()
        st.markdown(f'<span class="chip">{tag(CH.industry)}</span>', unsafe_allow_html=True)
        st.subheader(CH.title)
        st.info(CH.story)
        c1, c2, c3 = st.columns(3)
        c1.metric("Budget", f"${CH.budget:,.0f} / month")
        c0 = CH.checks[0]
        c2.metric("Steady-state target", f"p99 < {c0.p99_ms:g} ms", delta=f"success ≥ {c0.min_success:.1%}",
                  delta_color="off", delta_arrow="off")
        c3.metric("Hidden tests", f"{len(CH.checks)} chaos scenarios", help="Revealed after grading.")
        with st.expander("Hints"):
            for h in CH.hints:
                st.markdown(f"- {h}")

        last = ss.get("chal_last")
        graded_now = bool(last and last["cid"] == CH.id and last["dj"] == dj)

        st.markdown("#### Your design")
        plot(charts.architecture_figure(dcfg, None, THEME), key="ch_blueprint")
        if last and last["cid"] == CH.id and not graded_now:
            st.warning("Your design has changed since it was last graded. Submit again to see new results.")

        submitted, pred = prediction_form(dcfg, "ch_predict", "Will your design pass every hidden test?", allow_skip=True)
        if submitted:
            if cost > CH.budget:
                st.error("Over budget: reduce the design first.")
            else:
                with st.spinner("Running the hidden tests..."):
                    results, base_summ = grade(CH.id, dj)
                score = score_design(CH, design, results, opt_cost)
                ev = pg.record_attempt(ss.progress, CH.id, design, CH.budget, score, ORDER)
                ps, pev = None, None
                if pred is not None:
                    ps = score_prediction(pred, base_summ, score["all_pass"])
                    record_calibration(ps)
                    pev = pg.record_prediction(ss.progress, ps, ORDER)
                events = dict(xp=ev["xp_gained"] + (pev["xp_gained"] if pev else 0), stars=ev["stars_gained"],
                              badges=ev["new_badges"] + (pev["new_badges"] if pev else []),
                              level_up=ev["level_up"] or bool(pev and pev["level_up"]), level=(pev or ev)["level"])
                ss.chal_last = dict(cid=CH.id, dj=dj, design=design, results=results, score=score, ps=ps,
                                    events=events, celebrated=False)
                st.rerun()

        if graded_now:
            results, score, ps = last["results"], last["score"], last["ps"]
            st.divider()
            st.markdown("### Results")
            m = st.columns(4)
            m[0].metric("Score", f"{score['total_score']:.0f} / 100",
                        help="70 points for passing hidden tests, 30 for cost efficiency (only if every test passes).")
            m[1].metric("Reliability", f"{score['reliability']:.0f} / 70", delta=f"{score['passed']} of {score['total']} tests",
                        delta_color="off", delta_arrow="off")
            m[2].metric("Cost efficiency", f"{score['cost_pts']:.0f} / 30",
                        delta=(f"{score['efficiency']:.0%} of optimum" if score["efficiency"] else None),
                        delta_color="off", delta_arrow="off")
            m[3].metric("Your cost", f"${score['cost']:,.0f}",
                        delta=(f"optimum ${opt_cost:,.0f}" if opt_cost else None), delta_color="off", delta_arrow="off")
            n_st = pg.stars_for(score)
            hint = {0: "Pass every hidden test to earn a star.",
                    1: f"Passed every test. Two stars need {pg.STAR_EFFICIENCY[2]:.0%} cost efficiency.",
                    2: f"Three stars need {pg.STAR_EFFICIENCY[3]:.0%} cost efficiency, essentially the optimizer's design.",
                    3: "You matched the optimizer. Share it!"}[n_st]
            st.markdown(f"#### {'★' * n_st}{'☆' * (3 - n_st)}  {hint}")
            evs = last["events"]
            parts = ([f"+{evs['xp']} XP"] if evs["xp"] else []) + ([f"+{evs['stars']} ★"] if evs["stars"] else []) + \
                    [f"New badge: {pg.BADGES[b][0]}" for b in evs["badges"]] + \
                    ([f"Level up: {evs['level']['title']}"] if evs["level_up"] else [])
            if parts:
                st.success(" · ".join(parts))
            if not last.get("celebrated"):
                for b in evs["badges"]:
                    st.toast(f"Badge earned: {pg.BADGES[b][0]}", icon="\U0001F3C5")
                if evs["level_up"] or (evs["stars"] and n_st == 3):
                    st.balloons()
                last["celebrated"] = True
            st.caption(f"Attempt {ss.progress['attempts'].get(CH.id, 1)}. Best so far: "
                       f"{ss.progress['best'].get(CH.id, 0):.0f}. "
                       "Grading is deterministic: the same design always scores the same.")
            if not score["all_pass"]:
                st.warning("Cost points are awarded only when every test passes.")
            elif not opt_cost:
                st.caption("Optimizer data not found, so no cost points were awarded. Run `python tools/optimize.py`.")

            rows = []
            for chk, r in zip(CH.checks, results):
                rows.append({"Test": chk.name, "Result": "✓ Pass" if r["passed"] else "✕ Fail",
                             "Scenario": chk.blurb, "Target": chk.slo_text(),
                             "p99": f"{r['p99_ms']:,.0f} ms", "Success": f"{r['success']:.2%}",
                             "Write lag": f"{r['lag_p95_s']:.1f} s" if r["lag_p95_s"] is not None else "-",
                             "Why it failed": "; ".join(r["reasons"])})
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

            st.markdown("#### Share your result")
            ckey = f"{CH.id}|{dj}|{ss.theme}"
            if st.button("Create share card", key="mk_card"):
                pr = ss.progress["pred"]
                lv = pg.level_info(pg.xp_total(ss.progress))
                ss.card = (ckey, make_card(CH.title, score["total_score"], n_st, lv["title"], lv["level"],
                                           f"{score['passed']}/{score['total']}", score["cost"], opt_cost,
                                           design_lines(design), ss.theme,
                                           calibration=(pr["sum"] / pr["n"] if pr["n"] else None)))
            if ss.get("card") and ss.card[0] == ckey:
                st.image(ss.card[1], width=560)
                st.download_button("Download PNG", ss.card[1], file_name=f"{CH.id}_score_card.png", mime="image/png")

            if ps:
                show_prediction_score(ps)

            st.markdown("#### Where you landed in the design space")
            plot(charts.frontier_figure(opt.get("explored", []),
                                        dict(cost=score["cost"], passed=score["passed"], total=score["total"]),
                                        opt_cost, CH.budget, THEME), key="ch_frontier")
            st.caption("Each faint dot is a randomly sampled design graded on every test. "
                       "The star is the cheapest design the offline optimizer found that passes all tests.")

            with st.expander("Reveal the cheapest passing design"):
                if opt.get("optimum"):
                    od = opt["optimum"]
                    rows = [{"Knob": KNOB_LABELS[k], "Yours": str(design[k]), "Optimizer": str(od[k]),
                             "Same?": "✓" if design[k] == od[k] else "≠"} for k in KNOB_LABELS if k in CH.knobs]
                    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
                    bd = cost_breakdown(apply_design(CH.base, od))
                    st.caption("Optimizer cost: " + ", ".join(f"{k} ${v:,.0f}" for k, v in bd.items()) +
                               f" = ${sum(bd.values()):,.0f}/month. Found by simulating candidates from cheapest up "
                               f"({opt.get('screened', '?')} candidates after an analytic filter) and re-checking the "
                               "winner with two other random seeds.")
                else:
                    st.write("Optimizer data not available.")

            st.markdown("#### Replay a test")
            pick = st.selectbox("Test", range(len(CH.checks)), format_func=lambda i: CH.checks[i].name, key="ch_replay_pick")
            with st.spinner("Replaying..."):
                rres, rtl, rsumm, rfind = replay(CH.id, dj, int(pick))
            render_results(rres, rtl, rsumm, rfind, "ch", show_cost=False)

# ================================================================== about
with tab_about:
    st.markdown(
        """
### Model
- **Arrivals** are Poisson with a time-varying rate (for traffic spikes). **Service times** are exponential.
- **Tiers** are queues in tandem: client → (CDN) → load balancer → app replicas → cache → (write queue) → database.
  A worker is released before the next tier is called (like an async server).
- **Load balancing**: least-queue, round robin, random, or one shared queue (the ideal M/M/c pooling case).
- **CDN**: a share of reads is answered at the edge and never reaches the app tier.
- **Cache**: each read hits with probability *hit rate*; misses go to the database. Writes skip the cache.
- **Write queue**: a write is acknowledged once queued; consumers apply it later. Clients stay fast, but the
  *lag* (staleness) and the backlog are the price. A full queue rejects writes.
- **Database**: shards (independent primaries, a hot key can overload one), each with optional read replicas.
- **Clients give up** after the timeout; queues are bounded and drop overflow.
- **Latency percentiles count failures at the timeout value**, so an overloaded system can't look healthy by
  reporting only its lucky survivors.

### Challenge mode
Each challenge fixes a workload and hides several chaos tests. You pick a design with a few knobs. Grading runs every
test with fixed seeds, so a design always gets the same score: **70 points for tests passed, 30 for cost
efficiency** (cheapest passing design's cost ÷ yours, only if every test passes). The reference design is
found offline by `tools/optimize.py`: enumerate the designs, filter by napkin math, simulate in cost order, and
verify the winner on other seeds. Prices are illustrative: app replica $15 + $6 per worker, cache $50, CDN $40,
queue $30 + $4 per consumer, each database node $60 + $12 per connection.

### Campaign, XP and badges
Challenges unlock in order: earn one star (pass every hidden test) to open the next. Two stars need 80% cost
efficiency, three need 97%. XP comes from your best score per challenge, 40 per star, and a little for each
prediction (repeating a challenge cannot farm XP). Levels run from Intern to Distinguished Engineer. Progress lives
in your browser session; use **Save progress** in the sidebar to keep it between visits.

### Themes
Pick a color theme in the sidebar. Industry filters (E-commerce, Social, Fintech, Gaming) group scenarios and challenges.

### Predict-then-run
Before a run you commit four guesses: the busiest tier, its utilization, the p95 latency bucket, and whether the
design holds. They are scored against the steady-state run (without chaos events), because that is what napkin math
describes. The point is calibration: do you build intuition before you reach for a tool?

### Limits (stated honestly)
- No network latency, no retries, no replication lag on read replicas, no consistency model, and requests in a tier
  are independent. Cache invalidation on writes is not modeled.
- Fixed parameters and made-up prices: it shows *where* a design breaks and roughly *when*, not production numbers.
- The optimizer searches a small grid and screens designs with steady-state math, so "cheapest" means cheapest in that
  grid, not provably cheapest in the world.

### Extending it
Add a tier in `sim/engine.py` (a `Tier` plus a step in `_request`), a chart in `sim/charts.py`, a challenge in
`sim/challenges.py`, and tests in `tests/`.
        """
    )
