"""Load QC outputs for a run ID.

Supported inputs, checked in order under ``RUNS_DIR``:
  1. ``<run_id>.json``                     - metrics JSON from the existing QC pipeline
  2. ``<run_id>/qc.json``                  - same, nested in a run folder
  3. ``<run_id>/sequencing_summary.txt``   - raw MinKNOW/Dorado summary; metrics are computed here
"""

from __future__ import annotations

import csv
import json
import statistics
from pathlib import Path
from typing import IO

from . import config
from .schemas import QCMetrics


class RunNotFound(LookupError):
    pass


def load_run(run_id: str, runs_dir: Path | None = None) -> QCMetrics:
    runs_dir = runs_dir or config.RUNS_DIR
    run_id = run_id.strip()
    if not run_id or "/" in run_id or ".." in run_id:
        raise RunNotFound(f"Invalid run ID: {run_id!r}")

    for candidate in (runs_dir / f"{run_id}.json", runs_dir / run_id / "qc.json"):
        if candidate.exists():
            data = json.loads(candidate.read_text())
            data.setdefault("run_id", run_id)
            return QCMetrics.model_validate(data)

    summary = runs_dir / run_id / "sequencing_summary.txt"
    if summary.exists():
        with summary.open() as fh:
            return metrics_from_sequencing_summary(fh, run_id)

    raise RunNotFound(f"No QC output found for run {run_id!r} in {runs_dir}")


def list_runs(runs_dir: Path | None = None) -> list[str]:
    runs_dir = runs_dir or config.RUNS_DIR
    if not runs_dir.exists():
        return []
    ids = {p.stem for p in runs_dir.glob("*.json")}
    ids |= {p.name for p in runs_dir.iterdir() if p.is_dir()}
    return sorted(ids)


def _n50(lengths: list[int]) -> int:
    total = sum(lengths)
    acc = 0
    for length in sorted(lengths, reverse=True):
        acc += length
        if acc >= total / 2:
            return length
    return 0


def metrics_from_sequencing_summary(fh: IO[str], run_id: str, **overrides) -> QCMetrics:
    """Compute run metrics from a tab-separated ``sequencing_summary.txt``.

    Pore-level metrics are approximated from channel activity: a channel counts as
    active in an hour if it produced at least one read that hour.
    """
    reader = csv.DictReader(fh, delimiter="\t")
    lengths: list[int] = []
    qscores: list[float] = []
    passed = 0
    bases_per_sec: list[float] = []
    channels_by_hour: dict[int, set[str]] = {}

    for row in reader:
        length = int(float(row.get("sequence_length_template") or 0))
        lengths.append(length)
        qscores.append(float(row.get("mean_qscore_template") or 0))
        if str(row.get("passes_filtering", "")).upper() == "TRUE":
            passed += 1
        duration = float(row.get("duration") or 0)
        if duration > 0 and length > 0:
            bases_per_sec.append(length / duration)
        hour = int(float(row.get("start_time") or 0) // 3600)
        channels_by_hour.setdefault(hour, set()).add(row.get("channel", ""))

    if not lengths:
        raise ValueError("sequencing_summary.txt has no reads")

    hours = sorted(channels_by_hour)
    start_pores = len(channels_by_hour[hours[0]])
    hour_24 = min((h for h in hours if h >= 23), default=hours[-1])
    retention = len(channels_by_hour[hour_24]) / start_pores if start_pores else 0.0
    avg_active = statistics.mean(len(c) for c in channels_by_hour.values())

    data = dict(
        run_id=run_id,
        run_hours=float(hours[-1] + 1),
        total_reads=len(lengths),
        total_bases_gb=sum(lengths) / 1e9,
        read_n50=_n50(lengths),
        median_read_length=int(statistics.median(lengths)),
        mean_qscore=round(statistics.mean(qscores), 2),
        pct_pass_reads=passed / len(lengths),
        pores_at_start=start_pores,
        pore_retention_24h=round(retention, 3),
        # Without a pore-state log, approximate occupancy as mean active / peak active channels.
        pore_occupancy=round(avg_active / max(len(c) for c in channels_by_hour.values()), 3),
        pct_short_reads=sum(1 for x in lengths if x < 1000) / len(lengths),
        translocation_speed_bps=round(statistics.median(bases_per_sec), 1) if bases_per_sec else 400.0,
    )
    data.update(overrides)
    return QCMetrics.model_validate(data)
