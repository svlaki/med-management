"""Integration tests against a throwaway Neo4j container.

Run with: pytest -m integration (requires docker)
"""

import pytest
from testcontainers.neo4j import Neo4jContainer

from med_graph.graph.client import GraphClient

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def client():
    with Neo4jContainer("neo4j:5.26-community") as container:
        yield GraphClient(container.get_driver())


def test_apply_schema_is_idempotent(client):
    client.apply_schema()
    client.apply_schema()
    constraints = client.execute("SHOW CONSTRAINTS")
    names = {row["name"] for row in constraints}
    assert {"condition_id", "medication_rxcui", "side_effect_id"} <= names


def test_medication_rxcui_uniqueness_is_enforced(client):
    client.apply_schema()
    client.execute("MERGE (:Medication {rxcui: '36437', name: 'Zoloft'})")
    client.execute("MERGE (:Medication {rxcui: '36437', name: 'Zoloft'})")
    rows = client.execute(
        "MATCH (m:Medication {rxcui: '36437'}) RETURN count(m) AS count"
    )
    assert rows[0]["count"] == 1
