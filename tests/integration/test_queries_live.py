"""Query layer against a throwaway Neo4j container with a small known graph.

Run with: pytest -m integration (requires docker)
"""

import pytest
from testcontainers.neo4j import Neo4jContainer

from med_graph.graph.client import GraphClient
from med_graph.graph.loader import load_batch
from med_graph.models import (
    CausesEdge,
    Condition,
    EdgeSource,
    Medication,
    SideEffect,
    TreatsEdge,
)
from med_graph.queries.graph import condition_subgraph
from med_graph.queries.medications import (
    medications_by_side_effect,
    medications_for_condition,
    medications_without_side_effect,
    resolve_rxcui,
    side_effect_profile,
)
from med_graph.sources.base import SourceBatch

pytestmark = pytest.mark.integration

MDD = Condition(id="mdd", name="Major Depressive Disorder", icd10="F33")

BATCH = SourceBatch(
    medications=(
        Medication(rxcui="36437", name="sertraline", generic_name="sertraline"),
        Medication(rxcui="4493", name="fluoxetine", generic_name="fluoxetine"),
        Medication(rxcui="42347", name="bupropion", generic_name="bupropion"),
    ),
    side_effects=(
        SideEffect(id="nausea", name="Nausea", meddra_term="NAUSEA"),
        SideEffect(id="insomnia", name="Insomnia", meddra_term="INSOMNIA"),
        SideEffect(id="weight-gain", name="Weight gain", meddra_term="WEIGHT INCREASED"),
    ),
    treats=tuple(
        TreatsEdge(medication_rxcui=rxcui, condition_id="mdd", source=EdgeSource.RXCLASS)
        for rxcui in ("36437", "4493", "42347")
    ),
    causes=(
        CausesEdge(medication_rxcui="36437", side_effect_id="nausea",
                   source=EdgeSource.FAERS, report_count=13644, label_confirmed=True),
        CausesEdge(medication_rxcui="36437", side_effect_id="weight-gain",
                   source=EdgeSource.FAERS, report_count=800, label_confirmed=False),
        CausesEdge(medication_rxcui="4493", side_effect_id="nausea",
                   source=EdgeSource.FAERS, report_count=9120, label_confirmed=True),
        CausesEdge(medication_rxcui="4493", side_effect_id="insomnia",
                   source=EdgeSource.FAERS, report_count=5470, label_confirmed=True),
        # bupropion: insomnia only, notably no weight-gain edge
        CausesEdge(medication_rxcui="42347", side_effect_id="insomnia",
                   source=EdgeSource.FAERS, report_count=3000, label_confirmed=None),
    ),
)

# Isolated data for the tie-break test: two meds NOT linked to MDD (no TREATS
# edge) sharing one side effect with equal report counts, so the condition- and
# profile-scoped tests above are unaffected while the secondary sort is exercised.
TIE_BATCH = SourceBatch(
    medications=(
        Medication(rxcui="90001", name="zzz-tie", generic_name="zzz-tie"),
        Medication(rxcui="90002", name="aaa-tie", generic_name="aaa-tie"),
    ),
    side_effects=(SideEffect(id="tie-effect", name="Tie effect"),),
    causes=(
        CausesEdge(medication_rxcui="90001", side_effect_id="tie-effect",
                   source=EdgeSource.FAERS, report_count=1000),
        CausesEdge(medication_rxcui="90002", side_effect_id="tie-effect",
                   source=EdgeSource.FAERS, report_count=1000),
    ),
)


@pytest.fixture(scope="module")
def client():
    with Neo4jContainer("neo4j:5.26-community") as container:
        graph_client = GraphClient(container.get_driver())
        graph_client.apply_schema()
        graph_client.execute("MATCH (n) DETACH DELETE n")
        load_batch(graph_client, MDD, BATCH)
        load_batch(graph_client, MDD, TIE_BATCH)
        yield graph_client


def test_side_effect_profile_ranked_by_report_count(client):
    reports = side_effect_profile(client, "36437")
    assert [r.side_effect_id for r in reports] == ["nausea", "weight-gain"]
    assert reports[0].report_count == 13644
    assert reports[0].label_confirmed is True
    assert reports[1].label_confirmed is False


def test_side_effect_profile_confirmed_only_excludes_unconfirmed(client):
    # sertraline: nausea is label-confirmed, weight-gain is not
    reports = side_effect_profile(client, "36437", confirmed_only=True)
    assert [r.side_effect_id for r in reports] == ["nausea"]


def test_medications_for_condition_counts_side_effects(client):
    meds = medications_for_condition(client, "mdd")
    counts = {m.generic_name: m.side_effect_count for m in meds}
    assert counts == {"sertraline": 2, "fluoxetine": 2, "bupropion": 1}


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


def test_condition_subgraph_builds_bounded_payload(client):
    payload = condition_subgraph(client, "mdd", per_med=1)

    node_types = {n.type for n in payload.nodes}
    assert node_types == {"condition", "medication", "side_effect"}
    # 3 meds treat mdd => 3 treats edges; per_med=1 caps causes edges at 3
    treats = [e for e in payload.edges if e.kind == "treats"]
    causes = [e for e in payload.edges if e.kind == "causes"]
    assert len(treats) == 3
    assert len(causes) <= 3


def test_condition_subgraph_confirmed_only_filters_causes(client):
    payload = condition_subgraph(client, "mdd", confirmed_only=True, per_med=10)
    # every causes edge in the payload must be label-confirmed
    assert all(e.label_confirmed is True for e in payload.edges if e.kind == "causes")
