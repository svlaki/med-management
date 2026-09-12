"""Query layer against a throwaway Neo4j container with a small known graph.

Fixtures are written with the same Drug/DrugClass/MAY_TREAT/HAS_SIDE_EFFECT
schema that scripts/load_graph.py produces, so these tests exercise the real
shape of the graph the API serves.

Run with: pytest -m integration (requires docker)
"""

import pytest
from testcontainers.neo4j import Neo4jContainer

from med_graph.graph.client import GraphClient
from med_graph.queries.graph import condition_subgraph
from med_graph.queries.medications import (
    condition_exists,
    conditions_in_graph,
    drug_classes_in_graph,
    drug_conditions,
    drug_detail,
    medications_by_side_effect,
    medications_for_condition,
    medications_without_side_effect,
    resolve_rxcui,
    search_index,
    side_effect_profile,
)

pytestmark = pytest.mark.integration

DRUG_CLASSES = [
    {"id": "ssri", "name": "SSRI"},
    {"id": "ndri", "name": "NDRI"},
]
CONDITIONS = [
    {"id": "mdd", "name": "Major Depressive Disorder"},
    {"id": "sad", "name": "Seasonal Affective Disorder"},
]
DRUGS = [
    {"rxcui": "36437", "generic_name": "sertraline", "has_label": True,
     "product_type": "HUMAN PRESCRIPTION DRUG", "class_id": "ssri"},
    {"rxcui": "4493", "generic_name": "fluoxetine", "has_label": True,
     "product_type": "HUMAN PRESCRIPTION DRUG", "class_id": "ssri"},
    {"rxcui": "42347", "generic_name": "bupropion", "has_label": True,
     "product_type": "HUMAN PRESCRIPTION DRUG", "class_id": "ndri"},
    # Not linked to mdd, so the condition-scoped tests are unaffected; these two
    # share one side effect with equal report counts to exercise the tie-break.
    {"rxcui": "90001", "generic_name": "zzz-tie", "has_label": False,
     "product_type": None, "class_id": None},
    {"rxcui": "90002", "generic_name": "aaa-tie", "has_label": False,
     "product_type": None, "class_id": None},
]
SIDE_EFFECTS = [
    {"id": "nausea", "name": "Nausea", "meddra_term": "NAUSEA"},
    {"id": "insomnia", "name": "Insomnia", "meddra_term": "INSOMNIA"},
    {"id": "weight-gain", "name": "Weight gain", "meddra_term": "WEIGHT INCREASED"},
    {"id": "tie-effect", "name": "Tie effect", "meddra_term": None},
]
MAY_TREAT = [{"rxcui": r, "condition_id": "mdd"} for r in ("36437", "4493", "42347")]
MAY_PREVENT = [{"rxcui": "42347", "condition_id": "sad"}]
HAS_SIDE_EFFECT = [
    {"rxcui": "36437", "side_effect_id": "nausea", "report_count": 13644},
    {"rxcui": "36437", "side_effect_id": "weight-gain", "report_count": 800},
    {"rxcui": "4493", "side_effect_id": "nausea", "report_count": 9120},
    {"rxcui": "4493", "side_effect_id": "insomnia", "report_count": 5470},
    # bupropion: insomnia only, notably no weight-gain edge
    {"rxcui": "42347", "side_effect_id": "insomnia", "report_count": 3000},
    {"rxcui": "90001", "side_effect_id": "tie-effect", "report_count": 1000},
    {"rxcui": "90002", "side_effect_id": "tie-effect", "report_count": 1000},
]

LOAD_STATEMENTS = (
    ("UNWIND $rows AS row MERGE (dc:DrugClass {id: row.id}) SET dc.name = row.name",
     DRUG_CLASSES),
    ("UNWIND $rows AS row MERGE (c:Condition {id: row.id}) SET c.name = row.name",
     CONDITIONS),
    ("UNWIND $rows AS row MERGE (d:Drug {rxcui: row.rxcui}) "
     "SET d.generic_name = row.generic_name, d.has_label = row.has_label, "
     "d.product_type = row.product_type", DRUGS),
    ("UNWIND $rows AS row MERGE (s:SideEffect {id: row.id}) "
     "SET s.name = row.name, s.meddra_term = row.meddra_term", SIDE_EFFECTS),
    ("UNWIND $rows AS row WITH row WHERE row.class_id IS NOT NULL "
     "MATCH (d:Drug {rxcui: row.rxcui}) MATCH (dc:DrugClass {id: row.class_id}) "
     "MERGE (d)-[:BELONGS_TO]->(dc)", DRUGS),
    ("UNWIND $rows AS row MATCH (d:Drug {rxcui: row.rxcui}) "
     "MATCH (c:Condition {id: row.condition_id}) MERGE (d)-[:MAY_TREAT]->(c)",
     MAY_TREAT),
    ("UNWIND $rows AS row MATCH (d:Drug {rxcui: row.rxcui}) "
     "MATCH (c:Condition {id: row.condition_id}) MERGE (d)-[:MAY_PREVENT]->(c)",
     MAY_PREVENT),
    ("UNWIND $rows AS row MATCH (d:Drug {rxcui: row.rxcui}) "
     "MATCH (s:SideEffect {id: row.side_effect_id}) "
     "MERGE (d)-[r:HAS_SIDE_EFFECT]->(s) SET r.report_count = row.report_count",
     HAS_SIDE_EFFECT),
)


@pytest.fixture(scope="module")
def client():
    with Neo4jContainer("neo4j:5.26-community") as container:
        graph_client = GraphClient(container.get_driver())
        graph_client.apply_schema()
        graph_client.execute("MATCH (n) DETACH DELETE n")
        for statement, rows in LOAD_STATEMENTS:
            graph_client.execute(statement, {"rows": rows})
        yield graph_client


def test_side_effect_profile_ranked_by_report_count(client):
    reports = side_effect_profile(client, "36437")
    assert [r.side_effect_id for r in reports] == ["nausea", "weight-gain"]
    assert reports[0].report_count == 13644


def test_side_effect_profile_honours_limit(client):
    assert len(side_effect_profile(client, "36437", limit=1)) == 1


def test_medications_for_condition_counts_side_effects(client):
    meds = medications_for_condition(client, "mdd")
    counts = {m.generic_name: m.side_effect_count for m in meds}
    assert counts == {"sertraline": 2, "fluoxetine": 2, "bupropion": 1}


def test_medications_for_condition_resolves_drug_class_via_belongs_to(client):
    classes = {m.generic_name: m.drug_class for m in medications_for_condition(client, "mdd")}
    assert classes == {"sertraline": "SSRI", "fluoxetine": "SSRI", "bupropion": "NDRI"}


def test_medications_without_side_effect_excludes_matches(client):
    meds = medications_without_side_effect(client, "mdd", "weight")
    names = {m.generic_name for m in meds}
    # sertraline causes weight-gain and must be excluded; the other two remain
    assert names == {"fluoxetine", "bupropion"}


def test_medications_by_side_effect_ranked(client):
    causes = medications_by_side_effect(client, "insomnia")
    assert [c.generic_name for c in causes] == ["fluoxetine", "bupropion"]
    assert causes[0].report_count == 5470


def test_medications_by_side_effect_breaks_ties_by_generic_name(client):
    causes = medications_by_side_effect(client, "tie-effect")
    # equal report_count (1000) → secondary sort on generic_name ascending
    assert [c.generic_name for c in causes] == ["aaa-tie", "zzz-tie"]


def test_medications_by_side_effect_accepts_display_form_term(client):
    # "Tie effect" must slugify to the stored id "tie-effect"
    causes = medications_by_side_effect(client, "Tie effect")
    assert {c.generic_name for c in causes} == {"aaa-tie", "zzz-tie"}


def test_resolve_rxcui_is_case_insensitive(client):
    assert resolve_rxcui(client, "SERTRALINE") == "36437"
    assert resolve_rxcui(client, "unknown-drug") is None


def test_drug_detail_includes_class_and_label_flag(client):
    detail = drug_detail(client, "36437")
    assert detail.generic_name == "sertraline"
    assert detail.drug_class == "SSRI"
    assert detail.has_label is True
    assert drug_detail(client, "00000") is None


def test_drug_conditions_covers_both_therapeutic_edge_types(client):
    by_rela = {
        (c.rela, c.condition_id) for c in drug_conditions(client, "36437")
    } | {(c.rela, c.condition_id) for c in drug_conditions(client, "42347")}
    assert ("may_treat", "mdd") in by_rela
    assert ("may_prevent", "sad") in by_rela
    assert not any(rela == "ci_with" for rela, _ in by_rela)


def test_condition_exists_distinguishes_known_from_unknown(client):
    assert condition_exists(client, "mdd") is True
    assert condition_exists(client, "not-a-condition") is False


def test_conditions_and_drug_classes_are_listed(client):
    assert {c["id"] for c in conditions_in_graph(client)} == {"mdd", "sad"}
    assert {c["name"] for c in drug_classes_in_graph(client)} == {"SSRI", "NDRI"}


def test_search_index_spans_conditions_drugs_and_side_effects(client):
    entries = search_index(client)
    assert {e["type"] for e in entries} == {"condition", "drug", "side_effect"}
    labels = {e["label"] for e in entries}
    assert {"sertraline", "Major Depressive Disorder", "Nausea"} <= labels


def test_condition_subgraph_builds_bounded_payload(client):
    payload = condition_subgraph(client, "mdd", per_med=1)

    node_types = {n.type for n in payload.nodes}
    assert node_types == {"condition", "drug", "side_effect"}
    # 3 drugs treat mdd => 3 may_treat edges; per_med=1 caps side-effect edges at 3
    may_treat = [e for e in payload.edges if e.kind == "may_treat"]
    has_side_effect = [e for e in payload.edges if e.kind == "has_side_effect"]
    assert len(may_treat) == 3
    assert len(has_side_effect) <= 3


def test_condition_subgraph_labels_the_condition_with_its_name(client):
    payload = condition_subgraph(client, "mdd", per_med=1)
    condition = next(n for n in payload.nodes if n.type == "condition")
    assert condition.label == "Major Depressive Disorder"


def test_prevention_only_disorder_is_not_a_lone_node(client):
    # sad is reachable only through MAY_PREVENT; it must still bring its drug in.
    payload = condition_subgraph(client, "sad", per_med=1)

    assert [e.kind for e in payload.edges if e.kind == "may_prevent"] == ["may_prevent"]
    assert "drug:42347" in {n.id for n in payload.nodes}


def test_every_condition_in_the_graph_renders_at_least_one_edge(client):
    for condition in conditions_in_graph(client):
        payload = condition_subgraph(client, condition["id"], per_med=1)
        assert payload.edges, f"{condition['id']} renders as a lone node"


def test_condition_subgraph_per_med_caps_side_effects_per_drug(client):
    payload = condition_subgraph(client, "mdd", per_med=1)
    per_drug: dict[str, int] = {}
    for edge in payload.edges:
        if edge.kind == "has_side_effect":
            per_drug[edge.source] = per_drug.get(edge.source, 0) + 1
    assert all(count <= 1 for count in per_drug.values())
