"""Polling fragments keep the Streamlit server free of simulation CPU work."""
import hashlib
import json

import streamlit as st

from . import jobs
from .execution import decode
from .run_library_ui import library_key


@st.fragment(run_every="2s")
def _watch(job_id, owner):
    try:
        state, _ = jobs.poll(job_id, owner)
    except jobs.JobError:
        st.rerun(scope="app")
    if state == "complete":
        st.rerun(scope="app")
    st.info(f"Experiment {state}. Results will appear automatically; you can continue using the sidebar.")


def compute(kind, payload, local):
    if not jobs.enabled():
        try:
            return local()
        except ValueError as exc:
            st.error(str(exc))
            st.stop()
    owner = library_key()
    key = hashlib.sha256(json.dumps([kind, payload, owner], sort_keys=True).encode()).hexdigest()
    requests = st.session_state.setdefault("worker_jobs", {})
    try:
        if key not in requests:
            requests[key] = jobs.submit(kind, payload, owner)
            while len(requests) > 12:
                requests.pop(next(iter(requests)))
        state, data = jobs.poll(requests[key], owner)
        if state == "complete":
            return decode(data)
    except (jobs.JobError, ValueError) as exc:
        st.error(str(exc))
        if st.button("Retry experiment", key=f"retry_{key}"):
            requests.pop(key, None)
            st.rerun()
        st.stop()
    _watch(requests[key], owner)
    st.stop()
