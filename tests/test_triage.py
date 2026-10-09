from types import SimpleNamespace

import pytest

from nanopore_triage import config, rules
from nanopore_triage.graph import build_graph, triage
from nanopore_triage.qc_loader import RunNotFound, load_run
from nanopore_triage.schemas import Hypothesis, TriageAnalysis


class FakeClient:
    """Stands in for anthropic.Anthropic; records the request and returns a canned analysis."""

    def __init__(self, analysis=None, stop_reason="end_turn"):
        self.calls = []
        self.analysis, self.stop_reason = analysis, stop_reason
        self.beta = SimpleNamespace(messages=SimpleNamespace(parse=self._parse))

    def _parse(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(stop_reason=self.stop_reason, parsed_output=self.analysis)


def _analysis(**over):
    h = Hypothesis(rank=1, failure_mode="Contaminant pore blocking", confidence="high",
                   evidence=["pore_retention_24h=0.2"], supporting_run_ids=["PAW20001", "FAKE999"],
                   sop_refs=["SOP-LIB-02", "SOP-MADE-UP"], corrective_actions=["Re-clean with 0.8x beads"])
    base = dict(overall_status="fail", headline="Contaminants.", hypotheses=[h],
                rerun_recommendation="Re-clean and rerun.", data_salvageable=True)
    return TriageAnalysis(**(base | over))


@pytest.fixture
def llm_on(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.delenv("TRIAGE_OFFLINE", raising=False)


def test_flags_match_failure_signatures():
    codes = lambda rid: {f.code for f in rules.evaluate(load_run(rid))}
    assert {"RAPID_PORE_LOSS", "LOW_QSCORE"} <= codes("PAW31001")
    assert "LOW_OCCUPANCY" in codes("PAW31002")
    assert codes("PAW31003") == set()


def test_sequencing_summary_is_parsed():
    m = load_run("PAW31006")
    assert m.total_reads > 10_000 and 440 < m.translocation_speed_bps < 490
    assert "ABNORMAL_SPEED" in {f.code for f in rules.evaluate(m)}


def test_bad_run_id_rejected():
    with pytest.raises(RunNotFound):
        load_run("../etc/passwd")


def test_retrieval_finds_same_failure_mode(store):
    m = load_run("PAW31002")
    matches = store.similar_runs(m, rules.signature_text(m, rules.evaluate(m)))
    assert "Under-loaded" in matches[0].root_cause


def test_healthy_run_skips_llm(store, llm_on):
    client = FakeClient()
    state = triage("PAW31003", graph=build_graph(store, client))
    assert state["analysis"].overall_status == "pass" and client.calls == []


def test_llm_path_grounds_citations(store, llm_on):
    client = FakeClient(_analysis())
    state = triage("PAW31001", graph=build_graph(store, client))
    req = client.calls[0]
    assert req["model"] == config.MODEL and req["output_format"] is TriageAnalysis
    assert "PAW31001" in req["messages"][0]["content"]
    h = state["analysis"].hypotheses[0]
    assert "FAKE999" not in h.supporting_run_ids and "SOP-MADE-UP" not in h.sop_refs
    assert any("unverified" in w for w in state["warnings"])
    assert state["engine"] == config.MODEL


def test_llm_cannot_downgrade_critical_run(store, llm_on):
    client = FakeClient(_analysis(overall_status="pass"))
    state = triage("PAW31001", graph=build_graph(store, client))
    assert state["analysis"].overall_status == "fail"


def test_refusal_falls_back_to_rules(store, llm_on):
    client = FakeClient(None, stop_reason="refusal")
    state = triage("PAW31002", graph=build_graph(store, client))
    assert state["engine"] == "rules"
    assert state["analysis"].hypotheses[0].failure_mode.startswith("Under-loaded")
    assert "Under-loaded" in state["report_md"]


def test_offline_mode(store, monkeypatch):
    monkeypatch.setenv("TRIAGE_OFFLINE", "1")
    state = triage("PAW31005", graph=build_graph(store))
    assert state["engine"] == "rules" and state["analysis"].overall_status == "fail"
