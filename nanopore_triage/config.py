"""Runtime configuration, all overridable through environment variables."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DATA_DIR = Path(os.getenv("TRIAGE_DATA_DIR", ROOT / "data"))
RUNS_DIR = Path(os.getenv("TRIAGE_RUNS_DIR", DATA_DIR / "runs"))
SOP_DIR = Path(os.getenv("TRIAGE_SOP_DIR", DATA_DIR / "sops"))
HISTORY_FILE = Path(os.getenv("TRIAGE_HISTORY_FILE", DATA_DIR / "history" / "flagged_runs.jsonl"))
CHROMA_DIR = Path(os.getenv("TRIAGE_CHROMA_DIR", ROOT / ".chroma"))

MODEL = os.getenv("TRIAGE_MODEL", "claude-opus-5-5")
EFFORT = os.getenv("TRIAGE_EFFORT", "high")
TOP_K_RUNS = int(os.getenv("TRIAGE_TOP_K_RUNS", "5"))
TOP_K_SOPS = int(os.getenv("TRIAGE_TOP_K_SOPS", "4"))


def llm_enabled() -> bool:
    """LLM calls need credentials; without them the graph uses the rule-based fallback."""
    if os.getenv("TRIAGE_OFFLINE") == "1":
        return False
    return bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"))
