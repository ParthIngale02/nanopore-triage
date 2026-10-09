"""Claude call that turns metrics + retrieved context into ranked hypotheses."""

from __future__ import annotations

import json

import anthropic

from . import config
from .schemas import HistoricalMatch, QCFlag, QCMetrics, SOPChunk, TriageAnalysis

SYSTEM_PROMPT = """\
You are a sequencing core QC analyst triaging Oxford Nanopore runs for bench scientists.

You receive (1) run-level QC metrics, (2) deterministic QC flags computed from fixed thresholds,
(3) the most similar previously flagged runs from this lab, with their confirmed root causes and fixes,
and (4) relevant sections of the lab's SOPs.

Produce ranked failure-mode hypotheses, most likely first, with corrective actions a scientist can carry out
at the bench. Ground every claim:
- Evidence must cite specific metric values from the input.
- supporting_run_ids may only contain run IDs from the "Similar historical runs" section, and only when that
  run's symptoms actually resemble this run. An empty list is fine.
- sop_refs may only contain SOP IDs from the "SOP sections" section.
- When history and the metrics disagree, trust the metrics and say why in contrary_evidence.
- Several flags often share one upstream cause (e.g. contaminants cause both pore loss and low Q). Prefer the
  single explanation that accounts for the most flags, and rank it first.
- If the run is healthy, return overall_status "pass" with an empty or minimal hypothesis list.
- Keep corrective actions concrete (reagent, ratio, volume, instrument step), not generic advice.
- Put things the data cannot settle (e.g. "was the library frozen?") in open_questions.
Return 1-4 hypotheses."""


def _format_context(m: QCMetrics, flags: list[QCFlag], history: list[HistoricalMatch], sops: list[SOPChunk]) -> str:
    hist = "\n".join(
        f"- [{h.run_id}] similarity={h.similarity}\n  symptoms: {h.summary}\n  confirmed root cause: {h.root_cause}\n"
        f"  fix applied: {h.corrective_action}\n  outcome: {h.outcome}"
        for h in history
    ) or "(none retrieved)"
    sop_text = "\n\n".join(f"[{s.sop_id}] {s.title}\n{s.text}" for s in sops) or "(none retrieved)"
    flag_text = "\n".join(f"- {f.code} [{f.severity}] {f.metric}={f.value} (threshold {f.threshold}): {f.message}" for f in flags) or "(no flags)"
    return (
        f"## Run metrics\n```json\n{m.model_dump_json(indent=2)}\n```\n\n"
        f"## Deterministic QC flags\n{flag_text}\n\n"
        f"## Similar historical runs\n{hist}\n\n"
        f"## SOP sections\n{sop_text}\n\n"
        f"Triage run {m.run_id}."
    )


class RefusalError(RuntimeError):
    pass


def analyze(m: QCMetrics, flags: list[QCFlag], history: list[HistoricalMatch], sops: list[SOPChunk],
            client: anthropic.Anthropic | None = None) -> TriageAnalysis:
    client = client or anthropic.Anthropic()
    response = client.beta.messages.parse(
        model=config.MODEL,
        max_tokens=16000,
        system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": _format_context(m, flags, history, sops)}],
        thinking={"type": "adaptive"},
        output_config={"effort": config.EFFORT},
        output_format=TriageAnalysis,
        # Server-side fallback re-runs the request on a suitable model if a safety classifier declines.
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    if response.stop_reason == "refusal":
        raise RefusalError("Claude declined this request")
    if response.stop_reason == "max_tokens" or response.parsed_output is None:
        raise RuntimeError(f"Claude response incomplete (stop_reason={response.stop_reason})")
    return response.parsed_output


def debug_prompt(m, flags, history, sops) -> str:
    return json.dumps({"system": SYSTEM_PROMPT, "user": _format_context(m, flags, history, sops)}, indent=2)
