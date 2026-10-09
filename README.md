# Nanopore Run Triage Agent

An LLM triage agent for flagged Oxford Nanopore runs. A scientist enters a run ID (or uploads QC output) and gets a ranked list of failure-mode hypotheses with bench-level corrective actions. Each hypothesis is grounded in this lab's previously flagged runs (Chroma) and its SOPs. Built with **LangGraph** and the **Claude API** (`claude-opus-5-5`).

```
load_qc ─► extract_flags ─┬─► retrieve_history (Chroma, hybrid) ─┬─► hypothesize (Claude) ─► ground_check ─► render_report
                          └─► retrieve_sops    (Chroma)          ─┘
                          └─► healthy (no flags: skip retrieval + LLM)
```

| Node | What it does |
|---|---|
| `load_qc` | Loads `<run_id>.json` from the existing QC pipeline, or computes metrics from a raw `sequencing_summary.txt` |
| `extract_flags` | Applies deterministic thresholds (pore count, 24h retention, occupancy, N50, Q, pass rate, speed, temperature, model mismatch). These are reproducible and set the minimum status the LLM must respect |
| `retrieve_history` | Looks up similar past flagged runs: 50% semantic similarity (MiniLM embedding of a metric and flag "signature") + 50% normalised numeric distance on the raw metrics |
| `retrieve_sops` | Retrieves the SOP sections most relevant to the raised flags |
| `hypothesize` | Claude returns a schema-validated `TriageAnalysis` (structured outputs, adaptive thinking, server-side refusal fallback). If no key is set or the call fails, it falls back to a rule-based playbook |
| `ground_check` | Strips any cited run or SOP ID that wasn't in the retrieved context. Prevents the LLM from rating a run with critical flags as "pass" |
| `render_report` | Builds a markdown report: metrics, flags, ranked hypotheses with evidence, counter-evidence, actions and citations, plus the rerun decision |

Healthy runs skip the LLM entirely, so you don't pay for them. The UI has a **"Close the loop"** form: once the bench confirms a root cause, the run is added to the history so future triage can use it.

## Quick start

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
export ANTHROPIC_API_KEY=sk-ant-...          # optional; omit for rule-based mode
.venv/bin/python scripts/generate_demo_data.py   # synthetic history + runs (already committed)
.venv/bin/python -m nanopore_triage.cli seed     # build the Chroma index
.venv/bin/python -m nanopore_triage.cli triage PAW31001
.venv/bin/streamlit run app.py
.venv/bin/pytest -q
```

Demo runs: `PAW31001` (contaminants), `PAW31002` (under-loaded), `PAW31003` (healthy), `PAW31004` (fragmented DNA), `PAW31005` (bubble), `PAW31006` (raw summary, fast translocation).

## Bring your own data

* **Runs:** have your QC pipeline write `data/runs/<run_id>.json` with the fields in `QCMetrics` (`nanopore_triage/schemas.py`), or drop `data/runs/<run_id>/sequencing_summary.txt`. Point `TRIAGE_RUNS_DIR` at the pipeline's output directory.
* **History:** use JSONL with one line per confirmed flagged run: `{"metrics": {...}, "root_cause": "...", "corrective_action": "...", "outcome": "..."}`. Replace `data/history/flagged_runs.jsonl` and re-run `seed`.
* **SOPs:** add markdown files in `data/sops/`, split into sections by `## SOP-ID: Title` headings.
* **Thresholds:** edit `THRESHOLDS` in `nanopore_triage/rules.py` (the defaults are for MinION R10.4.1 + LSK114).

## Configuration

| Env var | Default | |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Enables the Claude path |
| `TRIAGE_MODEL` | `claude-opus-5-5` | |
| `TRIAGE_EFFORT` | `high` | `low`/`medium`/`high`/`xhigh`/`max` |
| `TRIAGE_OFFLINE` | — | `1` forces rule-based mode |
| `TRIAGE_RUNS_DIR`, `TRIAGE_SOP_DIR`, `TRIAGE_HISTORY_FILE`, `TRIAGE_CHROMA_DIR` | under `data/`, `.chroma/` | |
| `TRIAGE_EMBEDDER` | `minilm` | `hash` = dependency-free embedding for tests or air-gapped installs |

## Deploy

### Streamlit Community Cloud (from GitHub, free)
1. Push this repo to GitHub.
2. At [share.streamlit.io](https://share.streamlit.io), click **Create app**, pick the repo, branch `main`, main file `app.py`, and Python 3.12 under *Advanced settings*.
3. Under *Secrets*, add `ANTHROPIC_API_KEY = "sk-ant-..."`. Top-level secrets are exposed as environment variables.
4. The first boot seeds the Chroma index (it downloads the ~80 MB MiniLM model once).

Community Cloud storage is ephemeral, so runs added via "Close the loop" are lost on restart. Commit them to `data/history/flagged_runs.jsonl`, or use a host with a persistent volume. Keep the app private (Settings → Sharing) if it shows real lab data.

### Docker (Render, Fly.io, Cloud Run, HF Spaces)
The Docker image bakes in the embedding model and a seeded index, and serves Streamlit on `$PORT` (default 8501):

```bash
docker build -t nanopore-triage .
docker run -p 8501:8501 -e ANTHROPIC_API_KEY=sk-ant-... nanopore-triage
```

The same image runs on Render, Fly.io, Google Cloud Run, or a Hugging Face Docker Space (set `PORT=7860`). For run history that survives restarts, mount a volume at `/app/.chroma` and `/app/data/history`. Run data is lab-internal, so put the deployment behind authentication (private Space, Cloud Run IAM, or a VPN).
