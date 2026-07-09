"""Bounded subgraph payloads for visualization.

Returns a condition, the medications that treat it, and each medication's
top-N side effects as flat node/edge lists ready for a graph frontend.
"""

from pydantic import BaseModel, ConfigDict

from med_graph.graph.executor import GraphExecutor
from med_graph.queries.medications import medications_for_condition

# Top-N side effects per medication treating a condition, ranked by report
# volume. Meds with no (matching) side effects simply return no rows here;
# they are still present as nodes from the medications query.
# Uses the portable `CALL { WITH m ... }` subquery form (Neo4j 5.x) rather than
# the scoped `CALL (m) { ... }` syntax, which requires server 5.23+.
TOP_SIDE_EFFECTS_PER_MED = """
MATCH (c:Condition {id: $condition_id})<-[:TREATS]-(m:Medication)
CALL {
  WITH m
  MATCH (m)-[r:CAUSES]->(s:SideEffect)
  WHERE $confirmed_only = false OR r.label_confirmed = true
  RETURN s, r
  ORDER BY coalesce(r.report_count, 0) DESC, s.name
  LIMIT $per_med
}
RETURN m.rxcui AS rxcui, s.id AS side_effect_id, s.name AS side_effect_name,
       r.report_count AS report_count, r.label_confirmed AS label_confirmed
"""


class GraphNode(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    label: str
    type: str  # "condition" | "medication" | "side_effect"


class GraphEdge(BaseModel):
    model_config = ConfigDict(frozen=True)

    source: str
    target: str
    kind: str  # "treats" | "causes"
    report_count: int | None = None
    label_confirmed: bool | None = None


class GraphPayload(BaseModel):
    model_config = ConfigDict(frozen=True)

    nodes: list[GraphNode]
    edges: list[GraphEdge]


def condition_subgraph(
    client: GraphExecutor,
    condition_id: str,
    confirmed_only: bool = False,
    per_med: int = 10,
) -> GraphPayload:
    medications = medications_for_condition(client, condition_id)
    edge_rows = client.execute(
        TOP_SIDE_EFFECTS_PER_MED,
        {
            "condition_id": condition_id,
            "confirmed_only": confirmed_only,
            "per_med": per_med,
        },
    )

    condition_node_id = f"condition:{condition_id}"
    nodes: dict[str, GraphNode] = {
        condition_node_id: GraphNode(
            id=condition_node_id, label=condition_id.upper(), type="condition"
        )
    }
    edges: list[GraphEdge] = []

    for med in medications:
        med_node_id = f"medication:{med.rxcui}"
        nodes[med_node_id] = GraphNode(
            id=med_node_id, label=med.generic_name, type="medication"
        )
        edges.append(
            GraphEdge(source=med_node_id, target=condition_node_id, kind="treats")
        )

    for row in edge_rows:
        med_node_id = f"medication:{row['rxcui']}"
        effect_node_id = f"side_effect:{row['side_effect_id']}"
        nodes[effect_node_id] = GraphNode(
            id=effect_node_id, label=row["side_effect_name"], type="side_effect"
        )
        edges.append(
            GraphEdge(
                source=med_node_id,
                target=effect_node_id,
                kind="causes",
                report_count=row["report_count"],
                label_confirmed=row["label_confirmed"],
            )
        )

    return GraphPayload(nodes=list(nodes.values()), edges=edges)
