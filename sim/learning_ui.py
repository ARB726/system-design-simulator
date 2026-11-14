"""Evidence and repeatable experiments, separated from the main page."""
import hashlib
import json

import pandas as pd
import streamlit as st

from .coaching import pressure_evidence, suggest_experiment
from .config import config_from_dict
from .experiments import compare_seeds
from .job_ui import compute


def comparison_panel(baseline, candidate, key, label="Run paired comparison"):
    if baseline.workload != candidate.workload or baseline.events != candidate.events or baseline.app_only != candidate.app_only:
        st.info("Multi-seed comparison needs identical workloads and failure schedules. Restore a design and change only architecture or traffic policy.")
        return
    count = st.select_slider("Seeds per design", options=[3, 5, 7, 10], value=3, key=f"{key}_count")
    seeds = [(baseline.seed + i) % (2**63) for i in range(count)]
    st.caption(f"{count * 2} simulations, paired seeds {', '.join(map(str, seeds))}. "
               "Workload and failure schedule remain fixed. This can take longer than a single run.")
    payload = dict(baseline=baseline.to_dict(), candidate=candidate.to_dict(), seeds=seeds)
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    pending_key, result_key = f"{key}_pending", f"{key}_result"
    if st.button(label, key=f"{key}_run", icon=":material/science:"):
        st.session_state[pending_key] = payload
    pending = st.session_state.get(pending_key)
    if pending:
        def local():
            bar = st.progress(0.0, text="Starting paired simulations")
            try:
                return compare_seeds(config_from_dict(pending["baseline"]), config_from_dict(pending["candidate"]),
                                     pending["seeds"], progress=lambda f, text: bar.progress(f, text=text))
            finally:
                bar.empty()
        report = compute("compare_seeds", pending, local,
                         on_error=lambda: st.session_state.pop(pending_key, None))
        old_fingerprint = hashlib.sha256(json.dumps(pending, sort_keys=True).encode()).hexdigest()
        st.session_state[result_key] = (old_fingerprint, report)
        st.session_state.pop(pending_key, None)
    saved = st.session_state.get(result_key)
    if not saved:
        return
    old_fingerprint, report = saved
    if old_fingerprint != fingerprint:
        st.warning("Showing an earlier comparison. Run again for the current designs or seed count.")
    st.caption(report["caution"])
    st.write(f"Illustrative monthly cost: baseline ${report['baseline_cost']:,.0f}; candidate ${report['candidate_cost']:,.0f}.")
    st.dataframe(pd.DataFrame(report["aggregates"]), hide_index=True, width="stretch",
                 alt="Mean, sample standard deviation, and observed range for each design across seeds")
    st.markdown("**Paired differences: candidate minus baseline**")
    st.caption("Lower latency is better; higher throughput and success are better. A range spanning zero indicates mixed directions across these seeds. SD is sample standard deviation, not a confidence interval.")
    st.dataframe(pd.DataFrame(report["deltas"]), hide_index=True, width="stretch",
                 alt="Paired differences and number of seeds in which the candidate improved")
    with st.expander("Inspect every seed"):
        st.dataframe(pd.DataFrame(report["rows"]), hide_index=True, width="stretch", alt="Results per design and seed")
    st.download_button("Download multi-seed report", json.dumps(report, indent=2, allow_nan=False),
                       file_name="multi_seed_comparison.json", mime="application/json", key=f"{key}_download")
    return old_fingerprint == fingerprint


def coaching_panel(res, tl, summary, key):
    evidence = pressure_evidence(res, tl, summary)
    with st.expander("Inspect bottleneck evidence"):
        st.caption("Each row describes its tier's busiest three-bin post-warmup window. End-to-end latency includes all tiers. Sampled queues are averages within each timeline bin.")
        st.dataframe(pd.DataFrame(evidence), hide_index=True, width="stretch",
                     alt="Measured tier pressure, time window, sampled queues, and request outcomes")
    proposal = suggest_experiment(res.cfg, evidence)
    if proposal:
        with st.container(border=True):
            st.subheader("Test one change", icon=":material/science:")
            st.write(f"Change **{proposal['setting']}** from **{proposal['before']}** to **{proposal['after']}**.")
            st.caption(proposal["hypothesis"])
            comparison_panel(res.cfg, config_from_dict(proposal["candidate"]), f"{key}_suggested",
                             "Run suggested experiment across seeds")
    else:
        st.info("No queued tier showed sustained high utilization in the sampled windows, or its suggested capacity setting is already at the model limit. Use a controlled load sweep to investigate further.")


def local_sweep(function, *args, workers=1):
    bar = st.progress(0.0, text=f"Starting experiment with {workers} worker(s)")
    try:
        return function(*args, workers=workers, progress=lambda f, text: bar.progress(f, text=text))
    finally:
        bar.empty()
