import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["TRIAGE_EMBEDDER"] = "hash"  # no model download in tests


@pytest.fixture(scope="session")
def store(tmp_path_factory):
    from nanopore_triage import config
    from nanopore_triage.store import TriageStore

    s = TriageStore(tmp_path_factory.mktemp("chroma"))
    s.ingest_history_file(config.HISTORY_FILE)
    s.ingest_sops(config.SOP_DIR)
    return s
