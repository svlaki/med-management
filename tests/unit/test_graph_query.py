from med_graph.queries.graph import (
    DRUGS_FOR_CONDITION,
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


NAME = [{"name": "Major Depressive Disorder"}]
DRUGS = [
    {"rxcui": "36437", "generic_name": "sertraline", "drug_class": "SSRI",
     "rela": "MAY_TREAT"},
    {"rxcui": "42347", "generic_name": "bupropion", "drug_class": None,
     "rela": "MAY_TREAT"},
]
EFFECTS = [
    {"rxcui": "36437", "side_effect_id": "nausea", "side_effect_name": "Nausea",
     "report_count": 13644},
    {"rxcui": "42347", "side_effect_id": "insomnia", "side_effect_name": "Insomnia",
     "report_count": 3000},
]


def build_executor(drugs=None, effects=None, name=None):
    return FakeExecutor([
        NAME if name is None else name,
        DRUGS if drugs is None else drugs,
        EFFECTS if effects is None else effects,
    ])


def test_payload_has_condition_drug_and_side_effect_nodes():
    payload = condition_subgraph(build_executor(), "mdd")

    types = {node.type for node in payload.nodes}
    assert types == {"condition", "drug", "side_effect"}
    ids = {node.id for node in payload.nodes}
    assert "condition:mdd" in ids
    assert "drug:36437" in ids
    assert "side_effect:nausea" in ids


def test_condition_node_uses_the_display_name_not_the_slug():
    payload = condition_subgraph(build_executor(), "mdd")
    condition = next(n for n in payload.nodes if n.type == "condition")
    assert condition.label == "Major Depressive Disorder"


def test_condition_label_falls_back_to_the_id_when_unknown():
    payload = condition_subgraph(build_executor(name=[]), "mdd")
    condition = next(n for n in payload.nodes if n.type == "condition")
    assert condition.label == "mdd"


def test_drug_nodes_carry_their_class():
    payload = condition_subgraph(build_executor(), "mdd")
    by_id = {node.id: node for node in payload.nodes}
    assert by_id["drug:36437"].drug_class == "SSRI"
    assert by_id["drug:42347"].drug_class is None


def test_drug_nodes_are_deduped_but_shared_side_effects_collapse():
    effects = [
        {"rxcui": "36437", "side_effect_id": "nausea", "side_effect_name": "Nausea",
         "report_count": 100},
        {"rxcui": "42347", "side_effect_id": "nausea", "side_effect_name": "Nausea",
         "report_count": 80},
    ]
    payload = condition_subgraph(build_executor(effects=effects), "mdd")
    nausea_nodes = [n for n in payload.nodes if n.id == "side_effect:nausea"]
    assert len(nausea_nodes) == 1  # one node, two incoming edges


def test_edges_use_the_drug_schema_kinds():
    payload = condition_subgraph(build_executor(), "mdd")

    may_treat = [e for e in payload.edges if e.kind == "may_treat"]
    has_side_effect = [e for e in payload.edges if e.kind == "has_side_effect"]
    assert len(may_treat) == 2  # one per drug
    assert all(e.target == "condition:mdd" for e in may_treat)

    nausea_edge = next(e for e in has_side_effect if e.target == "side_effect:nausea")
    assert nausea_edge.source == "drug:36437"
    assert nausea_edge.report_count == 13644


def test_preventive_drugs_are_drawn_too():
    # A disorder reachable only through MAY_PREVENT must not render as a lone node.
    drugs = [
        {"rxcui": "42347", "generic_name": "bupropion", "drug_class": None,
         "rela": "MAY_PREVENT"},
    ]
    payload = condition_subgraph(build_executor(drugs=drugs, effects=[]), "alcoholism")

    assert {e.kind for e in payload.edges} == {"may_prevent"}
    assert "drug:42347" in {n.id for n in payload.nodes}


def test_a_drug_related_twice_yields_one_node_and_two_edges():
    drugs = [
        {"rxcui": "2598", "generic_name": "clonidine", "drug_class": None,
         "rela": "MAY_TREAT"},
        {"rxcui": "2598", "generic_name": "clonidine", "drug_class": None,
         "rela": "MAY_PREVENT"},
    ]
    payload = condition_subgraph(build_executor(drugs=drugs, effects=[]), "mdd")
    assert len([n for n in payload.nodes if n.id == "drug:2598"]) == 1
    assert {e.kind for e in payload.edges} == {"may_treat", "may_prevent"}


def test_per_med_limit_passed_to_edge_query():
    executor = build_executor()
    condition_subgraph(executor, "mdd", per_med=5)
    (_, edge_params) = executor.calls[2]
    assert edge_params == {"condition_id": "mdd", "per_med": 5}


def test_queries_are_parameterized():
    for query in (DRUGS_FOR_CONDITION, TOP_SIDE_EFFECTS_PER_MED):
        assert "$condition_id" in query
    assert "$per_med" in TOP_SIDE_EFFECTS_PER_MED


def test_queries_span_both_therapeutic_relationships():
    for query in (DRUGS_FOR_CONDITION, TOP_SIDE_EFFECTS_PER_MED):
        for rela in ("MAY_TREAT", "MAY_PREVENT"):
            assert rela in query
        assert "CI_WITH" not in query
    assert ":Medication" not in DRUGS_FOR_CONDITION


def test_drug_with_no_side_effects_still_appears_as_node():
    effects = [
        {"rxcui": "36437", "side_effect_id": "nausea", "side_effect_name": "Nausea",
         "report_count": 100},
    ]
    payload = condition_subgraph(build_executor(effects=effects), "mdd")
    assert "drug:42347" in {n.id for n in payload.nodes}
