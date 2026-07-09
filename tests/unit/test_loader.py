from med_graph.graph.loader import load_batch
from med_graph.models import (
    CausesEdge,
    Condition,
    EdgeSource,
    Frequency,
    Medication,
    SideEffect,
    TreatsEdge,
)
from med_graph.sources.base import SourceBatch

MDD = Condition(id="mdd", name="Major Depressive Disorder", icd10="F33")

BATCH = SourceBatch(
    medications=(
        Medication(rxcui="36437", name="sertraline", generic_name="sertraline"),
    ),
    side_effects=(SideEffect(id="nausea", name="Nausea"),),
    treats=(
        TreatsEdge(
            medication_rxcui="36437", condition_id="mdd", source=EdgeSource.RXCLASS
        ),
    ),
    causes=(
        CausesEdge(
            medication_rxcui="36437",
            side_effect_id="nausea",
            source=EdgeSource.OPENFDA_LABEL,
            frequency=Frequency.COMMON,
            report_count=13644,
            label_confirmed=True,
        ),
    ),
)


class RecordingClient:
    def __init__(self):
        self.calls = []

    def execute(self, query, parameters=None):
        self.calls.append((query, parameters or {}))
        return []


def queries_containing(client, fragment):
    return [(q, p) for q, p in client.calls if fragment in q]


def test_loads_all_node_and_edge_types():
    client = RecordingClient()

    counts = load_batch(client, MDD, BATCH)

    assert counts == {"medications": 1, "side_effects": 1, "treats": 1, "causes": 1}
    assert queries_containing(client, "MERGE (c:Condition")
    assert queries_containing(client, "MERGE (m:Medication")
    assert queries_containing(client, "MERGE (s:SideEffect")
    assert queries_containing(client, ":TREATS")
    assert queries_containing(client, ":CAUSES")


def test_all_writes_are_merge_based():
    client = RecordingClient()
    load_batch(client, MDD, BATCH)
    for query, _ in client.calls:
        assert "CREATE " not in query, f"non-idempotent write: {query}"


def test_edge_parameters_serialize_enums_to_strings():
    client = RecordingClient()
    load_batch(client, MDD, BATCH)

    (_, params) = queries_containing(client, ":CAUSES")[0]
    row = params["rows"][0]
    assert row["source"] == "openfda_label"
    assert row["frequency"] == "common"
    assert row["report_count"] == 13644
    assert row["label_confirmed"] is True


def test_empty_batch_writes_only_the_condition():
    client = RecordingClient()

    counts = load_batch(client, MDD, SourceBatch())

    assert counts == {"medications": 0, "side_effects": 0, "treats": 0, "causes": 0}
    assert len(client.calls) == 1
    assert "MERGE (c:Condition" in client.calls[0][0]
