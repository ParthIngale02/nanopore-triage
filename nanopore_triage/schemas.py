"""Typed data contracts shared by every node in the triage graph."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class QCMetrics(BaseModel):
    """Run-level QC metrics, as produced by the upstream Nanopore QC pipeline."""

    run_id: str
    flowcell_type: str = "FLO-MIN114"
    kit: str = "SQK-LSK114"
    device: str = "MinION"
    run_hours: float
    total_reads: int
    total_bases_gb: float
    read_n50: int
    median_read_length: int
    mean_qscore: float = Field(description="Mean read Q-score")
    pct_pass_reads: float = Field(description="Fraction 0-1 of reads passing the Q filter")
    pores_at_start: int = Field(description="Active pores from the initial mux scan")
    pore_retention_24h: float = Field(description="Fraction 0-1 of start pores still active at 24h (or run end)")
    pore_occupancy: float = Field(description="Fraction 0-1 of available pores actively sequencing")
    pct_short_reads: float = Field(description="Fraction 0-1 of reads < 1 kb")
    translocation_speed_bps: float = 400.0
    temp_deviation_c: float = 0.0
    basecall_model: str = "dna_r10.4.1_e8.2_400bps_sup@v5.0.0"
    notes: str = ""


Severity = Literal["info", "warning", "critical"]


class QCFlag(BaseModel):
    """A deterministic, threshold-based observation. Always explainable."""

    code: str
    metric: str
    value: float
    threshold: str
    severity: Severity
    message: str


class Hypothesis(BaseModel):
    rank: int
    failure_mode: str = Field(description="Short name, e.g. 'Pore blocking from sample contaminants'")
    confidence: Literal["high", "medium", "low"]
    evidence: list[str] = Field(description="Specific metric observations supporting this hypothesis")
    supporting_run_ids: list[str] = Field(description="IDs of retrieved historical runs that support it; only IDs from the provided context")
    sop_refs: list[str] = Field(description="IDs of SOP sections that apply; only IDs from the provided context")
    corrective_actions: list[str] = Field(description="Concrete bench steps, in order")
    contrary_evidence: list[str] = Field(default_factory=list, description="Observations that argue against this hypothesis")


class TriageAnalysis(BaseModel):
    """What the LLM returns. Rendered into the final report."""

    overall_status: Literal["pass", "review", "fail"]
    headline: str = Field(description="One sentence a bench scientist can act on")
    hypotheses: list[Hypothesis]
    rerun_recommendation: str
    data_salvageable: bool
    open_questions: list[str] = Field(default_factory=list, description="Things the scientist should check that the data cannot answer")


class HistoricalMatch(BaseModel):
    run_id: str
    root_cause: str
    corrective_action: str
    outcome: str
    similarity: float
    summary: str
    flags: list[str] = Field(default_factory=list)


class SOPChunk(BaseModel):
    sop_id: str
    title: str
    text: str
    relevance: float
