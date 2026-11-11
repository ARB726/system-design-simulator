"""Saved-run controls, kept separate from the simulation page."""
from __future__ import annotations

import json
import re
import sqlite3
from uuid import uuid4

import pandas as pd
import streamlit as st

from .history import RunStore, StorageError, compare_runs
from .auth import identity_key, required


def library_key() -> str:
    """The bookmark is a bearer link; keys are never used as filesystem paths."""
    if required():
        return identity_key(st.user)  # An arbitrary URL can never select another user's library.
    key = st.query_params.get("library", "")
    if not re.fullmatch(r"[a-f0-9]{32}", key):
        key = uuid4().hex
        st.query_params["library"] = key
    return key


def save_run_form(library, cfg, summary, findings, stale=False):
    with st.expander("Save this run", icon=":material/bookmark_add:"):
        st.caption("Save the results currently shown, including their configuration and cost.")
        if stale:
            st.caption("Your pending sidebar changes are not included. Run them first to save an updated design.")
        with st.form("save_run", clear_on_submit=True):
            name = st.text_input("Run name", placeholder="e.g. Baseline / Add a cache", max_chars=80,
                                 key="saved_run_name")
            save = st.form_submit_button("Save run", icon=":material/bookmark_add:")
        if save:
            try:
                RunStore().save(library, name, cfg, summary, findings)
            except ValueError as exc:
                st.error(str(exc))
            except (OSError, sqlite3.Error, StorageError):
                st.error("The run library is unavailable. You can still download the current summary below.")
            else:
                st.success("Run saved. Open Saved runs & compare to review it.")


def render_library(library, restore):
    st.subheader("Saved runs & compare", icon=":material/compare_arrows:")
    if required():
        st.caption("Your saved runs are associated with your signed-in account.")
    else:
        st.caption("Bookmark this page to reopen your library. Anyone with its full URL can access and edit it. "
                   "Runs are stored on this server; download backups before changing hosts.")
    try:
        runs = RunStore().list(library)
    except (OSError, sqlite3.Error, ValueError, StorageError):
        st.error("The run library is unavailable. Check that its storage directory is writable.")
        return
    if not runs:
        st.info("Save a baseline from the Results tab, change your design, then save a second run to compare.")
        return

    by_id = {r["id"]: r for r in runs}
    ids = list(by_id)
    labels = {r["id"]: f"{r['name']} / {r['created_at'][:19].replace('T', ' ')} UTC / {r['id'][:6]}" for r in runs}
    st.caption(f"{len(runs)} / 100 saved runs")
    table = [{"Name": r["name"], "Saved (UTC)": r["created_at"],
              "Served (rps)": r["summary"]["served_rps"],
              "Success (%)": 100 * r["summary"]["success_rate"],
              "p95 (ms)": r["summary"]["p95_ms"], "Cost ($/month)": r["cost"]} for r in runs]
    st.dataframe(pd.DataFrame(table).round(2), hide_index=True, width="stretch")

    def select(label, options, key, index=0):
        if st.session_state.get(key) not in options:
            st.session_state.pop(key, None)
        return st.selectbox(label, options, index=index, format_func=labels.get, key=key)

    selected = select("Saved run", ids, "library_run")
    run = by_id[selected]
    with st.container(horizontal=True):
        st.button("Load design into sandbox", icon=":material/settings_backup_restore:",
                  on_click=restore, args=(run["config"], run["name"]), key="restore_run")
        st.download_button("Download saved run", json.dumps(run, indent=2),
                           file_name=f"run_{run['id']}.json", mime="application/json")
    with st.expander("Saved configuration and findings"):
        st.json(run["config"])
        for finding in run["findings"]:
            st.markdown(f"**{finding['title']}**")
            st.write(finding["detail"])
    with st.expander("Delete selected run"):
        confirmed = st.checkbox("Delete this saved run permanently", key=f"delete_confirm_{selected}")
        if st.button("Delete run", disabled=not confirmed, key="delete_run"):
            try:
                RunStore().delete(library, selected)
            except (OSError, sqlite3.Error, StorageError):
                st.error("Could not delete the run. Please try again.")
            else:
                st.rerun()

    if len(runs) < 2:
        st.info("Save one more run to unlock side-by-side comparison.")
        return
    st.subheader("Compare designs")
    left, right = st.columns(2)
    with left:
        baseline_id = select("Baseline", ids, "compare_baseline", index=len(ids) - 1)
    with right:
        candidates = [i for i in ids if i != baseline_id]
        candidate_id = select("Candidate", candidates, "compare_candidate")
    comparison = compare_runs(by_id[baseline_id], by_id[candidate_id])
    for warning in comparison["warnings"]:
        st.warning(warning)
    st.dataframe(pd.DataFrame(comparison["metrics"]).round(2), hide_index=True, width="stretch")
    st.subheader("What changed, and what you traded")
    for note in comparison["notes"]:
        st.markdown(f"- {note}")
    if comparison["changes"]:
        st.dataframe(pd.DataFrame(comparison["changes"]), hide_index=True, width="stretch")
    else:
        st.caption("The saved configurations match. Any measured difference comes from the recorded results.")
    report = dict(baseline=by_id[baseline_id], candidate=by_id[candidate_id], comparison=comparison)
    st.download_button("Download comparison", json.dumps(report, indent=2),
                       file_name="design_comparison.json", mime="application/json")
