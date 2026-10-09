"""Deterministic QC checks.

These run before the LLM so that every hypothesis is anchored to an explicit,
reproducible observation. Thresholds target MinION R10.4.1 + LSK114 ligation runs;
adjust ``THRESHOLDS`` for other chemistries.
"""

from __future__ import annotations

from .schemas import HistoricalMatch, Hypothesis, QCFlag, QCMetrics, TriageAnalysis

THRESHOLDS = {
    "pores_at_start_warn": 1000,
    "pores_at_start_crit": 800,
    "pore_retention_warn": 0.55,
    "pore_retention_crit": 0.35,
    "occupancy_warn": 0.70,
    "occupancy_crit": 0.50,
    "n50_warn": 5000,
    "n50_crit": 2500,
    "short_reads_warn": 0.35,
    "qscore_warn": 14.0,
    "qscore_crit": 11.0,
    "pass_warn": 0.85,
    "pass_crit": 0.70,
    "speed_low": 360.0,
    "speed_high": 440.0,
    "temp_warn": 1.5,
    "yield_gb_per_hr_warn": 0.15,
}


def _flag(code, metric, value, threshold, severity, message) -> QCFlag:
    return QCFlag(code=code, metric=metric, value=round(float(value), 3), threshold=threshold, severity=severity, message=message)


def evaluate(m: QCMetrics) -> list[QCFlag]:
    t = THRESHOLDS
    flags: list[QCFlag] = []

    if m.pores_at_start < t["pores_at_start_crit"]:
        flags.append(_flag("LOW_START_PORES", "pores_at_start", m.pores_at_start, f"< {t['pores_at_start_crit']}", "critical",
                           "Initial active pore count is below the flow cell warranty level."))
    elif m.pores_at_start < t["pores_at_start_warn"]:
        flags.append(_flag("LOW_START_PORES", "pores_at_start", m.pores_at_start, f"< {t['pores_at_start_warn']}", "warning",
                           "Initial active pore count is lower than typical for a fresh flow cell."))

    if m.pore_retention_24h < t["pore_retention_crit"]:
        flags.append(_flag("RAPID_PORE_LOSS", "pore_retention_24h", m.pore_retention_24h, f"< {t['pore_retention_crit']}", "critical",
                           "Most pores were lost within 24h; this points to blocking, a bubble, or a membrane problem."))
    elif m.pore_retention_24h < t["pore_retention_warn"]:
        flags.append(_flag("RAPID_PORE_LOSS", "pore_retention_24h", m.pore_retention_24h, f"< {t['pore_retention_warn']}", "warning",
                           "Pores were lost faster than expected over 24h."))

    if m.pore_occupancy < t["occupancy_crit"]:
        flags.append(_flag("LOW_OCCUPANCY", "pore_occupancy", m.pore_occupancy, f"< {t['occupancy_crit']}", "critical",
                           "Most available pores sat idle; this usually means too little adapted library was loaded."))
    elif m.pore_occupancy < t["occupancy_warn"]:
        flags.append(_flag("LOW_OCCUPANCY", "pore_occupancy", m.pore_occupancy, f"< {t['occupancy_warn']}", "warning",
                           "Pore occupancy is below target."))

    if m.read_n50 < t["n50_crit"]:
        flags.append(_flag("SHORT_READS", "read_n50", m.read_n50, f"< {t['n50_crit']}", "critical",
                           "Read N50 is very short; this suggests fragmented input DNA or over-shearing."))
    elif m.read_n50 < t["n50_warn"]:
        flags.append(_flag("SHORT_READS", "read_n50", m.read_n50, f"< {t['n50_warn']}", "warning",
                           "Read N50 is shorter than expected for a gDNA ligation library."))

    if m.pct_short_reads > t["short_reads_warn"]:
        flags.append(_flag("HIGH_SHORT_FRACTION", "pct_short_reads", m.pct_short_reads, f"> {t['short_reads_warn']}", "warning",
                           "A large share of reads are < 1 kb (fragments, adapter dimers, or degraded DNA)."))

    if m.mean_qscore < t["qscore_crit"]:
        flags.append(_flag("LOW_QSCORE", "mean_qscore", m.mean_qscore, f"< {t['qscore_crit']}", "critical",
                           "Mean read Q-score is very low."))
    elif m.mean_qscore < t["qscore_warn"]:
        flags.append(_flag("LOW_QSCORE", "mean_qscore", m.mean_qscore, f"< {t['qscore_warn']}", "warning",
                           "Mean read Q-score is below target for SUP basecalling."))

    if m.pct_pass_reads < t["pass_crit"]:
        flags.append(_flag("LOW_PASS_RATE", "pct_pass_reads", m.pct_pass_reads, f"< {t['pass_crit']}", "critical",
                           "Less than 70% of reads pass the quality filter."))
    elif m.pct_pass_reads < t["pass_warn"]:
        flags.append(_flag("LOW_PASS_RATE", "pct_pass_reads", m.pct_pass_reads, f"< {t['pass_warn']}", "warning",
                           "The read pass rate is below target."))

    if not (t["speed_low"] <= m.translocation_speed_bps <= t["speed_high"]):
        flags.append(_flag("ABNORMAL_SPEED", "translocation_speed_bps", m.translocation_speed_bps,
                           f"outside {t['speed_low']:.0f}-{t['speed_high']:.0f}", "warning",
                           "Translocation speed is off nominal (temperature, buffer, or motor protein issue)."))

    if abs(m.temp_deviation_c) > t["temp_warn"]:
        flags.append(_flag("TEMP_EXCURSION", "temp_deviation_c", m.temp_deviation_c, f"|x| > {t['temp_warn']}", "warning",
                           "The flow cell temperature drifted from its setpoint during the run."))

    if m.run_hours > 0 and m.total_bases_gb / m.run_hours < t["yield_gb_per_hr_warn"]:
        flags.append(_flag("LOW_YIELD", "gb_per_hour", m.total_bases_gb / m.run_hours, f"< {t['yield_gb_per_hr_warn']}", "warning",
                           "Output per hour is low for a MinION flow cell."))

    if "dna_r9" in m.basecall_model and "FLO-MIN114" in m.flowcell_type:
        flags.append(_flag("MODEL_MISMATCH", "basecall_model", 0, "R10.4.1 flow cell needs an r10.4.1 model", "critical",
                           "The basecalling model does not match the flow cell chemistry."))

    return flags


def status_from_flags(flags: list[QCFlag]) -> str:
    if any(f.severity == "critical" for f in flags):
        return "fail"
    if flags:
        return "review"
    return "pass"


def signature_text(m: QCMetrics, flags: list[QCFlag]) -> str:
    """Natural-language fingerprint of a run, used as the embedding query/document."""
    flag_part = "; ".join(f"{f.code} ({f.severity}): {f.message}" for f in flags) or "No QC flags; healthy run."
    return (
        f"{m.device} {m.flowcell_type} {m.kit}. "
        f"Start pores {m.pores_at_start}, 24h pore retention {m.pore_retention_24h:.0%}, occupancy {m.pore_occupancy:.0%}. "
        f"N50 {m.read_n50} bp, short reads {m.pct_short_reads:.0%}, mean Q {m.mean_qscore:.1f}, pass {m.pct_pass_reads:.0%}, "
        f"speed {m.translocation_speed_bps:.0f} bp/s, temp dev {m.temp_deviation_c:+.1f} C, yield {m.total_bases_gb:.1f} Gb in {m.run_hours:.0f} h. "
        f"Flags: {flag_part} {m.notes}"
    ).strip()


# Normalisation ranges for the numeric similarity component of retrieval.
_VECTOR_SPEC = [
    ("pores_at_start", 400, 1700),
    ("pore_retention_24h", 0.0, 1.0),
    ("pore_occupancy", 0.0, 1.0),
    ("read_n50", 500, 30000),
    ("pct_short_reads", 0.0, 1.0),
    ("mean_qscore", 6.0, 22.0),
    ("pct_pass_reads", 0.0, 1.0),
    ("translocation_speed_bps", 250, 500),
    ("temp_deviation_c", -5.0, 5.0),
]


def metric_vector(m: QCMetrics | dict) -> list[float]:
    get = (lambda k: m[k]) if isinstance(m, dict) else (lambda k: getattr(m, k))
    out = []
    for key, lo, hi in _VECTOR_SPEC:
        v = (float(get(key)) - lo) / (hi - lo)
        out.append(min(max(v, 0.0), 1.0))
    return out


def numeric_similarity(a: list[float], b: list[float]) -> float:
    dist = sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5
    return 1.0 / (1.0 + 3.0 * dist)


# --- Rule-based fallback used when no LLM credentials are configured -------------

_PLAYBOOK = [
    ({"MODEL_MISMATCH"}, "Basecalling model / chemistry mismatch",
     ["Re-basecall the POD5 files with an r10.4.1 e8.2 SUP model in Dorado.", "Correct the run template so the default model is right."],
     ["SOP-BASECALL-01"]),
    ({"LOW_START_PORES"}, "Flow cell below spec at start (storage or shipping damage)",
     ["Run a flow cell check before loading and compare it with the delivery QC.", "File a warranty claim if the count is under the warranty threshold.", "Check fridge logs for flow cell storage (2-8 C)."],
     ["SOP-FC-01"]),
    ({"RAPID_PORE_LOSS", "LOW_QSCORE"}, "Pore blocking from sample contaminants",
     ["Repeat clean-up with a 0.4-0.8x bead ratio and fresh 80% ethanol.", "Check Nanodrop 260/230 (target > 2.0) and 260/280 (~1.8).", "Run a nuclease flush and reload if pores recover."],
     ["SOP-LIB-02", "SOP-FLUSH-01"]),
    ({"RAPID_PORE_LOSS"}, "Air bubble or membrane damage during priming",
     ["Inspect the flow cell for bubbles; re-prime slowly with the pipette set 20 uL under volume.", "Never introduce air at the priming port; check the sensor array image."],
     ["SOP-PRIME-01"]),
    ({"LOW_OCCUPANCY"}, "Under-loaded library (low adapted molarity)",
     ["Re-quantify the final library by Qubit and calculate molarity from the TapeStation size.", "Load 10-20 fmol for gDNA (35-50 fmol for amplicons).", "Check that the ligation adapter and LNB are fresh."],
     ["SOP-LIB-01"]),
    ({"SHORT_READS", "HIGH_SHORT_FRACTION"}, "Fragmented / degraded input DNA",
     ["Check input integrity on a TapeStation/Femto (target DIN > 7).", "Avoid vortexing; mix gDNA by flicking and use wide-bore tips.", "Consider a size selection (SRE kit or 0.45x beads)."],
     ["SOP-DNA-01"]),
    ({"TEMP_EXCURSION", "ABNORMAL_SPEED"}, "Temperature control issue affecting translocation",
     ["Check that the device has airflow and room temperature is 18-25 C.", "Look at the MinKNOW temperature trace; move the device away from heat sources."],
     ["SOP-ENV-01"]),
    ({"LOW_PASS_RATE"}, "Low basecall accuracy (signal quality)",
     ["Check that the basecalling model and kit match.", "Review the signal for noise; see whether the low pass rate correlates with pore loss."],
     ["SOP-BASECALL-01"]),
]


def fallback_analysis(m: QCMetrics, flags: list[QCFlag], history: list[HistoricalMatch]) -> TriageAnalysis:
    codes = {f.code for f in flags}
    hyps: list[Hypothesis] = []
    explained: set[str] = set()
    for required, name, actions, sops in _PLAYBOOK:
        overlap = required & codes
        if not overlap:
            continue
        # A hypothesis whose flags are all explained by a more specific one ranks lower.
        redundant = overlap <= explained
        confidence = "low" if redundant or overlap != required else "medium"
        explained |= overlap
        if "LOW_QSCORE" in explained:  # low Q drives the pass rate down; don't double-count it
            explained.add("LOW_PASS_RATE")
        hyps.append(Hypothesis(
            rank=0,
            failure_mode=name,
            confidence=confidence,
            evidence=[f"{f.message} ({f.metric}={f.value}, threshold {f.threshold})" for f in flags if f.code in overlap],
            supporting_run_ids=[h.run_id for h in history if overlap & set(h.flags)][:3],
            sop_refs=sops,
            corrective_actions=actions,
        ))
    hyps.sort(key=lambda h: (h.confidence != "medium", -len(h.evidence)))
    for i, h in enumerate(hyps, 1):
        h.rank = i
    status = status_from_flags(flags)
    return TriageAnalysis(
        overall_status=status,
        headline=("No QC flags were raised; the run looks healthy." if not hyps
                  else f"Most likely failure mode: {hyps[0].failure_mode} (rule-based, LLM not configured)."),
        hypotheses=hyps[:4],
        rerun_recommendation="No rerun needed." if status == "pass" else "Fix the top-ranked cause before re-running the library.",
        data_salvageable=m.pct_pass_reads > 0.5 and m.total_bases_gb > 1,
        open_questions=["Rule-based mode: set ANTHROPIC_API_KEY for LLM-ranked, history-grounded hypotheses."],
    )
