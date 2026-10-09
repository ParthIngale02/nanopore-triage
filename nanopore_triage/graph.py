"""LangGraph workflow: run ID -> diagnostic report.

    load_qc -> extract_flags -+-> retrieve_history -+-> hypothesize -> ground_check -> render_report
                              +-> retrieve_sops ----+
                              (healthy runs skip retrieval and the LLM entirely)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from . import config, llm, rules
from .qc_loader import load_run
from .schemas import HistoricalMatch, QCFlag, QCMetrics, SOPChunk, TriageAnalysis
from .store import TriageStore

log = logging.getLogger(__name__)


class TriageState(TypedDict, total=False):
    run_id: str
    metrics: QCMetrics
    flags: list[QCFlag]
    signature: str
    history: list[HistoricalMatch]
    sops: list[SOPChunk]
    analysis: TriageAnalysis
    engine: str
    warnings: list[str]
    report_md: str


def build_graph(store: TriageStore | None = None, llm_client=None):
    store = store or TriageStore()

    def load_qc(state: TriageState) -> TriageState:
        # Callers may pass metrics directly (e.g. an uploaded file); otherwise look up by ID.
        metrics = state.get("metrics") or load_run(state["run_id"])
        return {"metrics": metrics, "run_id": metrics.run_id, "warnings": []}

    def extract_flags(state: TriageState) -> TriageState:
        flags = rules.evaluate(state["metrics"])
        return {"flags": flags, "signature": rules.signature_text(state["metrics"], flags)}

    def route_after_flags(state: TriageState) -> list[str] | str:
        if not state["flags"]:
            return "healthy"
        return ["retrieve_history", "retrieve_sops"]

    def retrieve_history(state: TriageState) -> TriageState:
        return {"history": store.similar_runs(state["metrics"], state["signature"])}

    def retrieve_sops(state: TriageState) -> TriageState:
        query = " ".join(f.message for f in state["flags"])
        return {"sops": store.relevant_sops(query)}

    def hypothesize(state: TriageState) -> TriageState:
        m, flags = state["metrics"], state["flags"]
        history, sops = state.get("history", []), state.get("sops", [])
        warnings = list(state.get("warnings", []))
        if config.llm_enabled():
            try:
                return {"analysis": llm.analyze(m, flags, history, sops, client=llm_client), "engine": config.MODEL}
            except Exception as exc:  # degrade to rules rather than failing the scientist's request
                log.exception("LLM analysis failed")
                warnings.append(f"LLM analysis failed ({type(exc).__name__}: {exc}); showing rule-based triage instead.")
        analysis = rules.fallback_analysis(m, flags, history)
        return {"analysis": analysis, "engine": "rules", "warnings": warnings}

    def healthy(state: TriageState) -> TriageState:
        m = state["metrics"]
        return {
            "analysis": TriageAnalysis(
                overall_status="pass",
                headline=f"Run {m.run_id} passed every QC check ({m.total_bases_gb:.1f} Gb, N50 {m.read_n50:,} bp, mean Q{m.mean_qscore:.1f}).",
                hypotheses=[], rerun_recommendation="No action needed.", data_salvageable=True,
            ),
            "engine": "rules",
            "history": [], "sops": [],
        }

    def ground_check(state: TriageState) -> TriageState:
        """Remove citations to runs or SOPs that weren't in the retrieved context."""
        analysis = state["analysis"].model_copy(deep=True)
        known_runs = {h.run_id for h in state.get("history", [])}
        known_sops = {s.sop_id for s in state.get("sops", [])}
        if state.get("engine") == "rules":
            known_sops |= {s for *_, sops in rules._PLAYBOOK for s in sops}
        warnings = list(state.get("warnings", []))
        for h in analysis.hypotheses:
            bad_runs = [r for r in h.supporting_run_ids if r not in known_runs]
            bad_sops = [s for s in h.sop_refs if s not in known_sops]
            if bad_runs or bad_sops:
                warnings.append(f"Removed unverified citations from hypothesis {h.rank}: {bad_runs + bad_sops}")
            h.supporting_run_ids = [r for r in h.supporting_run_ids if r in known_runs]
            h.sop_refs = [s for s in h.sop_refs if s in known_sops]
        # The deterministic flags set a floor: the LLM can't call a critical run a pass.
        floor = rules.status_from_flags(state["flags"])
        order = ["pass", "review", "fail"]
        if order.index(analysis.overall_status) < order.index(floor):
            warnings.append(f"Status raised from '{analysis.overall_status}' to '{floor}' to match the deterministic flags.")
            analysis.overall_status = floor
        return {"analysis": analysis, "warnings": warnings}

    def render_report(state: TriageState) -> TriageState:
        return {"report_md": render_markdown(state)}

    g = StateGraph(TriageState)
    for name, fn in [("load_qc", load_qc), ("extract_flags", extract_flags), ("retrieve_history", retrieve_history),
                     ("retrieve_sops", retrieve_sops), ("hypothesize", hypothesize), ("healthy", healthy),
                     ("ground_check", ground_check), ("render_report", render_report)]:
        g.add_node(name, fn)
    g.add_edge(START, "load_qc")
    g.add_edge("load_qc", "extract_flags")
    g.add_conditional_edges("extract_flags", route_after_flags, ["retrieve_history", "retrieve_sops", "healthy"])
    g.add_edge(["retrieve_history", "retrieve_sops"], "hypothesize")
    g.add_edge("hypothesize", "ground_check")
    g.add_edge("healthy", "ground_check")
    g.add_edge("ground_check", "render_report")
    g.add_edge("render_report", END)
    return g.compile()


_STATUS_BADGE = {"pass": "PASS", "review": "NEEDS REVIEW", "fail": "FAIL"}


def render_markdown(state: TriageState) -> str:
    m, a = state["metrics"], state["analysis"]
    lines = [
        f"# Triage report: {m.run_id}",
        f"**Status: {_STATUS_BADGE[a.overall_status]}**: {a.headline}",
        "",
        f"_{m.device} · {m.flowcell_type} · {m.kit} · {m.run_hours:.0f} h · engine: {state.get('engine')} · "
        f"generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}_",
        "",
        "## Key metrics",
        "| Metric | Value |", "|---|---|",
        f"| Yield | {m.total_bases_gb:.2f} Gb ({m.total_reads:,} reads) |",
        f"| Read N50 / median | {m.read_n50:,} / {m.median_read_length:,} bp |",
        f"| Mean Q / pass rate | Q{m.mean_qscore:.1f} / {m.pct_pass_reads:.0%} |",
        f"| Pores at start / 24h retention | {m.pores_at_start} / {m.pore_retention_24h:.0%} |",
        f"| Pore occupancy | {m.pore_occupancy:.0%} |",
        f"| Reads < 1 kb | {m.pct_short_reads:.0%} |",
        f"| Speed / temp deviation | {m.translocation_speed_bps:.0f} bp/s / {m.temp_deviation_c:+.1f} °C |",
        "",
    ]
    if state["flags"]:
        lines += ["## QC flags", "| Severity | Flag | Value | Threshold |", "|---|---|---|---|"]
        lines += [f"| {f.severity} | {f.code} | {f.value} | {f.threshold} |" for f in state["flags"]]
        lines.append("")
    if a.hypotheses:
        lines.append("## Ranked hypotheses")
        for h in a.hypotheses:
            lines += [f"### {h.rank}. {h.failure_mode} ({h.confidence} confidence)", "**Evidence**"]
            lines += [f"- {e}" for e in h.evidence]
            if h.contrary_evidence:
                lines += ["**Against**"] + [f"- {e}" for e in h.contrary_evidence]
            lines += ["**Corrective actions**"] + [f"{i}. {s}" for i, s in enumerate(h.corrective_actions, 1)]
            refs = []
            if h.supporting_run_ids:
                refs.append("similar runs: " + ", ".join(h.supporting_run_ids))
            if h.sop_refs:
                refs.append("SOPs: " + ", ".join(h.sop_refs))
            if refs:
                lines.append(f"_Grounding: {'; '.join(refs)}_")
            lines.append("")
    lines += ["## Recommendation", f"- **Rerun:** {a.rerun_recommendation}",
              f"- **Data salvageable:** {'yes' if a.data_salvageable else 'no'}"]
    if a.open_questions:
        lines += ["", "## Open questions for the bench"] + [f"- {q}" for q in a.open_questions]
    if state.get("history"):
        lines += ["", "## Similar historical runs", "| Run | Similarity | Root cause | Outcome |", "|---|---|---|---|"]
        lines += [f"| {h.run_id} | {h.similarity:.2f} | {h.root_cause} | {h.outcome} |" for h in state["history"]]
    if state.get("warnings"):
        lines += ["", "## System notes"] + [f"- {w}" for w in state["warnings"]]
    return "\n".join(lines) + "\n"


def triage(run_id: str | None = None, metrics: QCMetrics | None = None, graph=None) -> TriageState:
    graph = graph or build_graph()
    init: TriageState = {"run_id": run_id or (metrics.run_id if metrics else "")}
    if metrics is not None:
        init["metrics"] = metrics
    return graph.invoke(init)
