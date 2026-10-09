"""Streamlit front end: paste a run ID (or upload QC output), get a diagnostic report."""

from __future__ import annotations

import io
import json

import streamlit as st

from nanopore_triage import config
from nanopore_triage.cli import seed
from nanopore_triage.graph import build_graph, triage
from nanopore_triage.qc_loader import RunNotFound, list_runs, metrics_from_sequencing_summary
from nanopore_triage.schemas import QCMetrics
from nanopore_triage.store import TriageStore

st.set_page_config(page_title="Nanopore Run Triage", page_icon="🧬", layout="wide")


@st.cache_resource
def get_store() -> TriageStore:
    store = TriageStore()
    if store.counts()["runs"] == 0:
        seed(store)  # first boot of a fresh container
    return store


@st.cache_resource
def get_graph():
    return build_graph(get_store())


store = get_store()

with st.sidebar:
    st.header("Knowledge base")
    c = store.counts()
    st.metric("Historical flagged runs", c["runs"])
    st.metric("SOP sections", c["sops"])
    st.caption(f"Engine: **{config.MODEL}**" if config.llm_enabled() else "Engine: **rule-based** (no ANTHROPIC_API_KEY set)")
    available = list_runs()
    if available:
        st.caption("Runs available: " + ", ".join(available))

st.title("Nanopore run triage")
st.write("Enter a run ID from the QC pipeline, or upload a QC file, to get ranked failure-mode hypotheses "
         "grounded in previously flagged runs and lab SOPs.")

tab_id, tab_upload = st.tabs(["Run ID", "Upload QC output"])
state = None

with tab_id:
    with st.form("by_id"):
        run_id = st.text_input("Run ID", placeholder="e.g. PAW31001")
        go = st.form_submit_button("Triage run", type="primary")
    if go and run_id:
        with st.spinner("Extracting metrics, retrieving history, generating hypotheses..."):
            try:
                state = triage(run_id, graph=get_graph())
            except RunNotFound as e:
                st.error(str(e))

with tab_upload:
    up = st.file_uploader("qc.json or sequencing_summary.txt", type=["json", "txt", "tsv"])
    up_id = st.text_input("Run ID for this upload", value="UPLOAD")
    if up and st.button("Triage upload", type="primary"):
        raw = up.getvalue().decode()
        try:
            if up.name.endswith(".json"):
                metrics = QCMetrics.model_validate(json.loads(raw) | {"run_id": up_id})
            else:
                metrics = metrics_from_sequencing_summary(io.StringIO(raw), up_id)
        except Exception as e:  # malformed upload; show the error rather than a stack trace
            st.error(f"Could not parse {up.name}: {e}")
        else:
            with st.spinner("Running triage..."):
                state = triage(metrics=metrics, graph=get_graph())

if state:
    st.session_state["last"] = state

state = st.session_state.get("last")
if state:
    a = state["analysis"]
    color = {"pass": "green", "review": "orange", "fail": "red"}[a.overall_status]
    st.markdown(f"### :{color}[{a.overall_status.upper()}]: {a.headline}")
    st.markdown(state["report_md"].split("\n", 2)[2])  # skip the duplicated title/status lines
    st.download_button("Download report (.md)", state["report_md"], file_name=f"{state['run_id']}_triage.md")

    if a.overall_status != "pass":
        st.divider()
        st.subheader("Close the loop")
        st.caption("Once the root cause is confirmed at the bench, add this run to the history so future triage can learn from it.")
        with st.form("confirm"):
            options = [h.failure_mode for h in a.hypotheses] + ["Other"]
            choice = st.selectbox("Confirmed root cause", options)
            other = st.text_input("If other, describe")
            fix = st.text_area("Corrective action taken", value=a.hypotheses[0].corrective_actions[0] if a.hypotheses else "")
            outcome = st.text_input("Outcome of rerun", placeholder="e.g. rerun yield 20 Gb, retention 0.7")
            if st.form_submit_button("Add to history"):
                cause = other if choice == "Other" else choice
                store.add_historical_run(state["metrics"], cause, fix, outcome or "pending")
                with config.HISTORY_FILE.open("a") as fh:
                    fh.write(json.dumps({"metrics": state["metrics"].model_dump(), "root_cause": cause,
                                         "corrective_action": fix, "outcome": outcome or "pending"}) + "\n")
                st.success(f"{state['run_id']} added to history ({store.counts()['runs']} runs).")
