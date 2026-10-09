"""Chroma vector store for historical flagged runs and lab SOPs.

Run retrieval is hybrid: semantic similarity between run "signatures" (text
fingerprints of metrics + flags) blended with a normalised numeric distance over
the raw metrics, so two runs with the same symptoms rank close even when the
free-text notes differ.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from pathlib import Path

import chromadb
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

from . import config, rules
from .schemas import HistoricalMatch, QCMetrics, SOPChunk

RUNS_COLLECTION = "flagged_runs"
SOPS_COLLECTION = "lab_sops"
SEMANTIC_WEIGHT = 0.5


class HashEmbedding(EmbeddingFunction[Documents]):
    """Dependency-free bag-of-words embedding for tests and air-gapped installs."""

    DIM = 384

    def __init__(self) -> None:
        pass

    def __call__(self, input: Documents) -> Embeddings:
        out = []
        for text in input:
            vec = [0.0] * self.DIM
            for tok in re.findall(r"[a-z0-9_]+", text.lower()):
                h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
                vec[h % self.DIM] += 1.0
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            out.append([v / norm for v in vec])
        return out

    @staticmethod
    def name() -> str:
        return "triage_hash"

    def get_config(self) -> dict:
        return {}

    @staticmethod
    def build_from_config(config: dict) -> "HashEmbedding":
        return HashEmbedding()


def _embedder() -> EmbeddingFunction:
    if os.getenv("TRIAGE_EMBEDDER", "minilm") == "hash":
        return HashEmbedding()
    return DefaultEmbeddingFunction()  # all-MiniLM-L6-v2 via ONNX, runs locally


class TriageStore:
    def __init__(self, path: Path | None = None) -> None:
        self.client = chromadb.PersistentClient(path=str(path or config.CHROMA_DIR))
        ef = _embedder()
        meta = {"hnsw:space": "cosine"}
        self.runs = self.client.get_or_create_collection(RUNS_COLLECTION, embedding_function=ef, metadata=meta)
        self.sops = self.client.get_or_create_collection(SOPS_COLLECTION, embedding_function=ef, metadata=meta)

    # --- ingestion ---------------------------------------------------------------

    def add_historical_run(self, metrics: QCMetrics, root_cause: str, corrective_action: str, outcome: str) -> None:
        flags = rules.evaluate(metrics)
        self.runs.upsert(
            ids=[metrics.run_id],
            documents=[rules.signature_text(metrics, flags)],
            metadatas=[{
                "root_cause": root_cause,
                "corrective_action": corrective_action,
                "outcome": outcome,
                "flags": ",".join(f.code for f in flags),
                "vector": json.dumps(rules.metric_vector(metrics)),
            }],
        )

    def ingest_history_file(self, path: Path) -> int:
        n = 0
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            self.add_historical_run(
                QCMetrics.model_validate(rec["metrics"]),
                rec["root_cause"], rec["corrective_action"], rec["outcome"],
            )
            n += 1
        return n

    def ingest_sops(self, sop_dir: Path) -> int:
        """Split each markdown SOP on '## SOP-XXX: Title' headings; one chunk per section."""
        ids, docs, metas = [], [], []
        for md in sorted(sop_dir.glob("*.md")):
            for match in re.finditer(r"^## (SOP-[A-Z0-9-]+): (.+?)\n(.*?)(?=^## SOP-|\Z)", md.read_text(), re.S | re.M):
                sop_id, title, body = match.group(1), match.group(2).strip(), match.group(3).strip()
                ids.append(sop_id)
                docs.append(f"{title}\n{body}")
                metas.append({"title": title, "source": md.name})
        if ids:
            self.sops.upsert(ids=ids, documents=docs, metadatas=metas)
        return len(ids)

    def counts(self) -> dict[str, int]:
        return {"runs": self.runs.count(), "sops": self.sops.count()}

    # --- retrieval ---------------------------------------------------------------

    def similar_runs(self, metrics: QCMetrics, signature: str, k: int = config.TOP_K_RUNS) -> list[HistoricalMatch]:
        total = self.runs.count()
        if total == 0:
            return []
        # Over-fetch semantically, then re-rank with the numeric component.
        res = self.runs.query(query_texts=[signature], n_results=min(total, k * 4),
                              include=["documents", "metadatas", "distances"])
        qvec = rules.metric_vector(metrics)
        matches = []
        for rid, doc, meta, dist in zip(res["ids"][0], res["documents"][0], res["metadatas"][0], res["distances"][0]):
            if rid == metrics.run_id:
                continue
            semantic = 1.0 - dist
            numeric = rules.numeric_similarity(qvec, json.loads(meta["vector"]))
            score = SEMANTIC_WEIGHT * semantic + (1 - SEMANTIC_WEIGHT) * numeric
            matches.append(HistoricalMatch(
                run_id=rid, root_cause=meta["root_cause"], corrective_action=meta["corrective_action"],
                outcome=meta["outcome"], similarity=round(score, 3), summary=doc,
                flags=[f for f in meta.get("flags", "").split(",") if f],
            ))
        matches.sort(key=lambda m: m.similarity, reverse=True)
        return matches[:k]

    def relevant_sops(self, query: str, k: int = config.TOP_K_SOPS) -> list[SOPChunk]:
        total = self.sops.count()
        if total == 0:
            return []
        res = self.sops.query(query_texts=[query], n_results=min(total, k), include=["documents", "metadatas", "distances"])
        return [
            SOPChunk(sop_id=sid, title=meta["title"], text=doc, relevance=round(1.0 - dist, 3))
            for sid, doc, meta, dist in zip(res["ids"][0], res["documents"][0], res["metadatas"][0], res["distances"][0])
        ]
