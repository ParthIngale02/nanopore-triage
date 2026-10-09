"""Generate synthetic demo data: flagged-run history, new runs to triage, one raw summary.

Replace data/history/flagged_runs.jsonl and data/runs/ with real exports from your
QC pipeline once you've confirmed the format (see README "Bring your own data").
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

rng = random.Random(42)

BASE = dict(
    flowcell_type="FLO-MIN114", kit="SQK-LSK114", device="MinION", run_hours=72.0,
    pores_at_start=1450, pore_retention_24h=0.78, pore_occupancy=0.88, read_n50=14000,
    median_read_length=6500, mean_qscore=18.5, pct_pass_reads=0.93, pct_short_reads=0.12,
    translocation_speed_bps=400.0, temp_deviation_c=0.2, basecall_model="dna_r10.4.1_e8.2_400bps_sup@v5.0.0",
)

# failure mode -> (metric overrides, root cause, corrective action, outcome, notes pool)
MODES = {
    "contaminant_blocking": (
        dict(pore_retention_24h=(0.15, 0.32), mean_qscore=(12.0, 14.5), pct_pass_reads=(0.72, 0.84), pore_occupancy=(0.65, 0.8)),
        "Pore blocking from carryover contaminants (ethanol / phenol / polysaccharide)",
        "Repeated 0.8x AMPure clean-up with fresh 80% ethanol, air-dried beads 30 s; nuclease flush + reload",
        "Rerun recovered: 24h retention 0.71, yield 18 Gb",
        ["Plant leaf extraction, CTAB.", "Nanodrop 260/230 = 1.4.", "Ethanol smell noted in eluate.", "Soil metagenome sample."],
    ),
    "underloading": (
        dict(pore_occupancy=(0.25, 0.48), pore_retention_24h=(0.65, 0.85)),
        "Under-loaded library: adapted library molarity too low",
        "Re-quantified by Qubit HS and TapeStation; loaded 20 fmol instead of ~5 fmol",
        "Rerun occupancy 0.86, yield tripled",
        ["Final library 3 ng/uL.", "Loaded by mass not molarity.", "Low-input protocol.", ""],
    ),
    "fragmented_dna": (
        dict(read_n50=(1200, 3200), median_read_length=(600, 1500), pct_short_reads=(0.45, 0.7), pore_occupancy=(0.8, 0.92)),
        "Fragmented input DNA (DIN < 6)",
        "Re-extracted with wide-bore tips, no vortexing; size-selected with SRE kit",
        "Rerun N50 16 kb",
        ["Sample went through 3 freeze-thaw cycles.", "FFPE-derived.", "Vortexed during resuspension.", "Old extraction (6 months)."],
    ),
    "bubble": (
        dict(pore_retention_24h=(0.05, 0.25), pores_at_start=(1200, 1450), mean_qscore=(17.0, 19.0)),
        "Air bubble introduced during priming, destroying the membrane over part of the array",
        "Re-trained on priming: remove 20-30 uL from priming port, dial pipette 20 uL short; new flow cell",
        "Next run normal",
        ["Pore loss sudden at 3 h, spatially clustered.", "New lab member loaded.", "Sudden drop in channel map region.", ""],
    ),
    "old_flowcell": (
        dict(pores_at_start=(520, 790), pore_retention_24h=(0.55, 0.7)),
        "Flow cell below warranty pore count (expired / stored at wrong temperature)",
        "Warranty claim filed; replacement flow cell checked before loading",
        "Replacement had 1510 pores; run normal",
        ["Flow cell 4 months past delivery.", "Fridge excursion logged last week.", "Flow cell check skipped.", ""],
    ),
    "temperature": (
        dict(temp_deviation_c=(2.2, 4.5), translocation_speed_bps=(440, 480), mean_qscore=(14.5, 16.5), pct_pass_reads=(0.8, 0.88)),
        "Device overheating (poor airflow / hot room) shifting translocation speed",
        "Moved device off the warm instrument shelf, ensured vent clearance; room AC fixed",
        "Rerun speed 402 bp/s, Q18",
        ["Lab temperature 29 C during heatwave.", "Device placed next to a thermocycler.", "", "Laptop vent blocked."],
    ),
    "model_mismatch": (
        dict(basecall_model="dna_r9.4.1_450bps_hac", mean_qscore=(7.0, 9.0), pct_pass_reads=(0.2, 0.4)),
        "Wrong basecalling model (R9.4.1 model on R10.4.1 data)",
        "Re-basecalled POD5 with dna_r10.4.1_e8.2_400bps_sup@v5.0.0 in Dorado",
        "Q18.3 after re-basecalling, no rerun needed",
        ["Run template copied from old R9 protocol.", ""],
    ),
    "dimers": (
        dict(pct_short_reads=(0.4, 0.6), read_n50=(4500, 8000), pore_occupancy=(0.75, 0.9), mean_qscore=(16.0, 18.0)),
        "Adapter/ligation dimers from excess adapter and inadequate clean-up",
        "Used LFB (not SFB) wash to remove short fragments; reduced adapter volume",
        "Short read fraction dropped to 10%",
        ["Short Fragment Buffer used by mistake.", "Many reads ~100-200 bp.", ""],
    ),
}


def sample(overrides: dict) -> dict:
    m = dict(BASE)
    for k, v in BASE.items():
        if isinstance(v, float) and k not in ("run_hours",):
            m[k] = round(v * rng.uniform(0.95, 1.05), 3)
    m["pores_at_start"] = int(BASE["pores_at_start"] * rng.uniform(0.92, 1.08))
    m["read_n50"] = int(BASE["read_n50"] * rng.uniform(0.8, 1.3))
    m["median_read_length"] = int(m["read_n50"] * rng.uniform(0.4, 0.5))
    for k, v in overrides.items():
        if isinstance(v, tuple):
            lo, hi = v
            m[k] = int(rng.uniform(lo, hi)) if isinstance(lo, int) else round(rng.uniform(lo, hi), 3)
        else:
            m[k] = v
    for k in ("pore_retention_24h", "pore_occupancy", "pct_pass_reads", "pct_short_reads"):
        m[k] = min(m[k], 0.99)
    m["temp_deviation_c"] = round(m["temp_deviation_c"] if "temp_deviation_c" in overrides else rng.uniform(-0.6, 0.6), 2)
    # Yield follows from active pores, retention and occupancy.
    effective = m["pores_at_start"] * (0.4 + 0.6 * m["pore_retention_24h"]) * m["pore_occupancy"]
    m["total_bases_gb"] = round(effective * m["translocation_speed_bps"] * 3600 * m["run_hours"] * 0.25 / 1e9, 2)
    m["total_reads"] = int(m["total_bases_gb"] * 1e9 / max(m["read_n50"] * 0.6, 300))
    return m


def main() -> None:
    hist_dir, runs_dir = ROOT / "data" / "history", ROOT / "data" / "runs"
    hist_dir.mkdir(parents=True, exist_ok=True)
    runs_dir.mkdir(parents=True, exist_ok=True)

    records = []
    n = 1
    for mode, (ov, cause, fix, outcome, notes) in MODES.items():
        for _ in range(6 if mode != "model_mismatch" else 3):
            m = sample(ov)
            m["run_id"] = f"PAW{20000 + n:05d}"
            m["notes"] = rng.choice(notes)
            records.append({"metrics": m, "failure_mode": mode, "root_cause": cause,
                            "corrective_action": fix, "outcome": outcome})
            n += 1
    with (hist_dir / "flagged_runs.jsonl").open("w") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")

    # New, unlabelled runs a scientist would paste in.
    new_runs = {
        "PAW31001": sample(MODES["contaminant_blocking"][0]) | {"notes": "Fungal gDNA, column extraction."},
        "PAW31002": sample(MODES["underloading"][0]) | {"notes": ""},
        "PAW31003": sample({}) | {"notes": "Routine human gDNA."},
        "PAW31004": sample(MODES["fragmented_dna"][0] | {"pore_occupancy": (0.45, 0.55)}) | {"notes": "Low input, sample from freezer -20 C."},
        "PAW31005": sample(MODES["bubble"][0]) | {"notes": "Pores dropped sharply around hour 2."},
    }
    for rid, m in new_runs.items():
        m["run_id"] = rid
        (runs_dir / f"{rid}.json").write_text(json.dumps(m, indent=2))

    write_sequencing_summary(runs_dir / "PAW31006" / "sequencing_summary.txt")
    print(f"wrote {len(records)} historical runs, {len(new_runs) + 1} new runs")


def write_sequencing_summary(path: Path, channels: int = 1300, hours: int = 30) -> None:
    """Raw summary for a temperature-excursion-like run with fast translocation."""
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = ["read_id", "channel", "start_time", "duration", "passes_filtering",
            "sequence_length_template", "mean_qscore_template"]
    with path.open("w") as fh:
        fh.write("\t".join(cols) + "\n")
        rid = 0
        for h in range(hours):
            active = int(channels * (1 - 0.018 * h))
            for ch in rng.sample(range(1, channels + 1), active):
                for _ in range(2):
                    length = max(150, int(rng.lognormvariate(8.6, 0.9)))
                    q = rng.gauss(15.2, 2.0)
                    speed = rng.gauss(465, 15)
                    fh.write("\t".join(map(str, [
                        f"r{rid:08d}", ch, round(h * 3600 + rng.uniform(0, 3599), 1), round(length / speed, 3),
                        "TRUE" if q >= 10 else "FALSE", length, round(q, 2),
                    ])) + "\n")
                    rid += 1


if __name__ == "__main__":
    main()
