from med_graph.queries.graph import (
    TOP_SIDE_EFFECTS_PER_MED,
    condition_subgraph,
)


class FakeExecutor:
    """Returns queued result sets in call order."""

    def __init__(self, result_sets):
        self._result_sets = list(result_sets)
        self.calls = []

    def execute(self, query, parameters=None):
        self.calls.append((query, parameters or {}))
        return self._result_sets.pop(0)


def build_executor(meds, edges):
    return FakeExecutor([meds, edges])


MEDS = [
    {"rxcui": "36437", "generic_name": "sertraline", "drug_class": None,
     "side_effect_count": 2},
    {"rxcui": "42347", "generic_name": "bupropion", "drug_class": None,
     "side_effect_count": 1},
]
EDGES = [
    {"rxcui": "36437", "side_effect_id": "nausea", "side_effect_name": "Nausea",
     "report_count": 13644, "label_confirmed": True},
    {"rxcui": "42347", "side_effect_id": "insomnia", "side_effect_name": "Insomnia",
     "report_count": 3000, "label_confirmed": True},
]


def test_payload_has_condition_medication_and_side_effect_nodes():
    payload = condition_subgraph(build_executor(MEDS, EDGES), "mdd")

    types = {node.type for node in payload.nodes}
    assert types == {"condition", "medication", "side_effect"}
    ids = {node.id for node in payload.nodes}
    assert "condition:mdd" in ids
    assert "medication:36437" in ids
    assert "side_effect:nausea" in ids


def test_medication_nodes_are_deduped_but_shared_side_effects_collapse():
    edges = [
        {"rxcui": "36437", "side_effect_id": "nausea", "side_effect_name": "Nausea",
         "report_count": 100, "label_confirmed": True},
        {"rxcui": "42347", "side_effect_id": "nausea", "side_effect_name": "Nausea",
         "report_count": 80, "label_confirmed": False},
    ]
    payload = condition_subgraph(build_executor(MEDS, edges), "mdd")

    nausea_nodes = [n for n in payload.nodes if n.id == "side_effect:nausea"]
    assert len(nausea_nodes) == 1  # one node, two incoming edges


def test_edges_include_treats_and_causes_with_provenance():
    payload = condition_subgraph(build_executor(MEDS, EDGES), "mdd")

    treats = [e for e in payload.edges if e.kind == "treats"]
    causes = [e for e in payload.edges if e.kind == "causes"]
    assert len(treats) == 2  # one per medication
    assert all(e.target == "condition:mdd" for e in treats)

    nausea_edge = next(e for e in causes if e.target == "side_effect:nausea")
    assert nausea_edge.source == "medication:36437"
    assert nausea_edge.report_count == 13644
    assert nausea_edge.label_confirmed is True


def test_confirmed_only_and_limit_passed_to_edge_query():
    executor = build_executor(MEDS, EDGES)

    condition_subgraph(executor, "mdd", confirmed_only=True, per_med=5)

    (_, edge_params) = executor.calls[1]
    assert edge_params == {
        "condition_id": "mdd",
        "confirmed_only": True,
        "per_med": 5,
    }


def test_edge_query_is_parameterized():
    assert "$condition_id" in TOP_SIDE_EFFECTS_PER_MED
    assert "$per_med" in TOP_SIDE_EFFECTS_PER_MED
    assert "$confirmed_only" in TOP_SIDE_EFFECTS_PER_MED


def test_medication_with_no_side_effects_still_appears_as_node():
    # bupropion has an edge here removed; it must still be a node from the meds query
    edges = [
        {"rxcui": "36437", "side_effect_id": "nausea", "side_effect_name": "Nausea",
         "report_count": 100, "label_confirmed": True},
    ]
    payload = condition_subgraph(build_executor(MEDS, edges), "mdd")

    assert "medication:42347" in {n.id for n in payload.nodes}
