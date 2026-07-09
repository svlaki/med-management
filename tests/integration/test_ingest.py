"""Loader idempotency against a throwaway Neo4j container.

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
from med_graph.sources.base import SourceBatch

pytestmark = pytest.mark.integration

MDD = Condition(id="mdd", name="Major Depressive Disorder", icd10="F33")

BATCH = SourceBatch(
    medications=(
        Medication(rxcui="36437", name="sertraline", generic_name="sertraline"),
        Medication(rxcui="4493", name="fluoxetine", generic_name="fluoxetine"),
    ),
    side_effects=(SideEffect(id="nausea", name="Nausea", meddra_term="NAUSEA"),),
    treats=(
        TreatsEdge(
            medication_rxcui="36437", condition_id="mdd", source=EdgeSource.RXCLASS
        ),
        TreatsEdge(
            medication_rxcui="4493", condition_id="mdd", source=EdgeSource.RXCLASS
        ),
    ),
    causes=(
        CausesEdge(
            medication_rxcui="36437",
            side_effect_id="nausea",
            source=EdgeSource.FAERS,
            report_count=13644,
        ),
        CausesEdge(
            medication_rxcui="4493",
            side_effect_id="nausea",
            source=EdgeSource.FAERS,
            report_count=9120,
        ),
    ),
)


@pytest.fixture(scope="module")
def client():
    with Neo4jContainer("neo4j:5.26-community") as container:
        graph_client = GraphClient(container.get_driver())
        graph_client.apply_schema()
        yield graph_client


def test_repeated_ingest_is_idempotent(client):
    client.execute("MATCH (n) DETACH DELETE n")
    load_batch(client, MDD, BATCH)
    load_batch(client, MDD, BATCH)

    rows = client.execute(
        "MATCH (m:Medication)-[r:TREATS]->(c:Condition {id: 'mdd'}) "
        "RETURN count(DISTINCT m) AS meds, count(r) AS edges"
    )
    assert rows[0] == {"meds": 2, "edges": 2}

    causes = client.execute(
        "MATCH (:Medication)-[r:CAUSES]->(s:SideEffect) "
        "RETURN count(DISTINCT s) AS effects, count(r) AS edges"
    )
    assert causes[0] == {"effects": 1, "edges": 2}

    counts = client.execute(
        "MATCH (m:Medication {rxcui: '36437'})-[r:CAUSES]->(:SideEffect {id: 'nausea'}) "
        "RETURN r.report_count AS report_count"
    )
    assert counts[0]["report_count"] == 13644
