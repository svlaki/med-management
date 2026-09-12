"""Bounded subgraph payloads for visualization.

Returns a condition, every drug related to it, and each drug's top-N side
effects as flat node/edge lists ready for a graph frontend.

Both therapeutic relationships are drawn, not just MAY_TREAT: a disorder
reachable only through MAY_PREVENT would otherwise render as a node with no
edges at all. Contraindications are not part of the graph.
"""

from pydantic import BaseModel, ConfigDict

from med_graph.graph.executor import GraphExecutor

CONDITION_NODE = """
MATCH (c:Condition {id: $condition_id})
RETURN c.name AS name
"""

DRUGS_FOR_CONDITION = """
MATCH (d:Drug)-[r:MAY_TREAT|MAY_PREVENT]->(c:Condition {id: $condition_id})
OPTIONAL MATCH (d)-[:BELONGS_TO]->(dc:DrugClass)
RETURN d.rxcui AS rxcui, d.generic_name AS generic_name,
       dc.name AS drug_class, type(r) AS rela
ORDER BY generic_name
"""

TOP_SIDE_EFFECTS_PER_MED = """
MATCH (c:Condition {id: $condition_id})<-[:MAY_TREAT|MAY_PREVENT]-(d:Drug)
CALL (d) {
  MATCH (d)-[r:HAS_SIDE_EFFECT]->(s:SideEffect)
  RETURN s, r
  ORDER BY coalesce(r.report_count, 0) DESC, s.name
  LIMIT $per_med
}
RETURN DISTINCT d.rxcui AS rxcui, s.id AS side_effect_id, s.name AS side_effect_name,
       r.report_count AS report_count
"""


class GraphNode(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    label: str
    type: str  # "condition" | "drug" | "side_effect" | "drug_class"
    drug_class: str | None = None


class GraphEdge(BaseModel):
    model_config = ConfigDict(frozen=True)

    source: str
    target: str
    kind: str  # "may_treat" | "may_prevent" | "has_side_effect" | "belongs_to"
    report_count: int | None = None


class GraphPayload(BaseModel):
    model_config = ConfigDict(frozen=True)

    nodes: list[GraphNode]
    edges: list[GraphEdge]


DRUG_INFO = """
MATCH (d:Drug {rxcui: $rxcui})
OPTIONAL MATCH (d)-[:BELONGS_TO]->(dc:DrugClass)
RETURN d.rxcui AS rxcui, d.generic_name AS generic_name, dc.name AS drug_class
"""

DRUG_CONDITIONS_NEIGHBORHOOD = """
MATCH (d:Drug {rxcui: $rxcui})-[r:MAY_TREAT|MAY_PREVENT]->(c:Condition)
RETURN c.id AS cond_id, c.name AS cond_name, type(r) AS rela
"""

DRUG_SIDE_EFFECTS_NEIGHBORHOOD = """
MATCH (d:Drug {rxcui: $rxcui})-[r:HAS_SIDE_EFFECT]->(s:SideEffect)
RETURN s.id AS se_id, s.name AS se_name, r.report_count AS report_count
ORDER BY coalesce(r.report_count, 0) DESC, s.name
LIMIT $per_med
"""

CONDITION_NEIGHBORHOOD = """
MATCH (c:Condition {id: $condition_id})
OPTIONAL MATCH (d:Drug)-[r:MAY_TREAT|MAY_PREVENT]->(c)
OPTIONAL MATCH (d)-[:BELONGS_TO]->(dc:DrugClass)
RETURN c.id AS cond_id, c.name AS cond_name,
       d.rxcui AS rxcui, d.generic_name AS generic_name,
       dc.name AS drug_class, type(r) AS rela
"""

SIDE_EFFECT_NEIGHBORHOOD = """
MATCH (s:SideEffect {id: $side_effect_id})
OPTIONAL MATCH (d:Drug)-[r:HAS_SIDE_EFFECT]->(s)
OPTIONAL MATCH (d)-[:BELONGS_TO]->(dc:DrugClass)
RETURN s.id AS se_id, s.name AS se_name,
       d.rxcui AS rxcui, d.generic_name AS generic_name,
       dc.name AS drug_class, r.report_count AS report_count
"""


def node_neighborhood(
    client: GraphExecutor,
    node_type: str,
    node_id: str,
    per_med: int = 10,
) -> GraphPayload:
    """Return a node and all its immediate neighbors as a graph payload."""
    nodes: dict[str, GraphNode] = {}
    edges: list[GraphEdge] = []

    if node_type == "drug":
        info_rows = client.execute(DRUG_INFO, {"rxcui": node_id})
        if not info_rows:
            return GraphPayload(nodes=[], edges=[])
        drug_node_id = f"drug:{node_id}"
        nodes[drug_node_id] = GraphNode(
            id=drug_node_id,
            label=info_rows[0]["generic_name"],
            type="drug",
            drug_class=info_rows[0]["drug_class"],
        )
        cond_rows = client.execute(
            DRUG_CONDITIONS_NEIGHBORHOOD, {"rxcui": node_id}
        )
        for row in cond_rows:
            cond_node_id = f"condition:{row['cond_id']}"
            nodes[cond_node_id] = GraphNode(
                id=cond_node_id, label=row["cond_name"], type="condition"
            )
            edges.append(
                GraphEdge(
                    source=drug_node_id,
                    target=cond_node_id,
                    kind=row["rela"].lower(),
                )
            )
        se_rows = client.execute(
            DRUG_SIDE_EFFECTS_NEIGHBORHOOD,
            {"rxcui": node_id, "per_med": per_med},
        )
        for row in se_rows:
            se_node_id = f"side_effect:{row['se_id']}"
            nodes[se_node_id] = GraphNode(
                id=se_node_id, label=row["se_name"], type="side_effect"
            )
            edges.append(
                GraphEdge(
                    source=drug_node_id,
                    target=se_node_id,
                    kind="has_side_effect",
                    report_count=row["report_count"],
                )
            )

    elif node_type == "condition":
        rows = client.execute(
            CONDITION_NEIGHBORHOOD, {"condition_id": node_id}
        )
        if not rows:
            return GraphPayload(nodes=[], edges=[])
        cond_node_id = f"condition:{node_id}"
        nodes[cond_node_id] = GraphNode(
            id=cond_node_id, label=rows[0]["cond_name"], type="condition"
        )
        for row in rows:
            if row["rxcui"] is not None:
                drug_node_id = f"drug:{row['rxcui']}"
                nodes[drug_node_id] = GraphNode(
                    id=drug_node_id,
                    label=row["generic_name"],
                    type="drug",
                    drug_class=row["drug_class"],
                )
                edges.append(
                    GraphEdge(
                        source=drug_node_id,
                        target=cond_node_id,
                        kind=row["rela"].lower(),
                    )
                )

    elif node_type == "side_effect":
        rows = client.execute(
            SIDE_EFFECT_NEIGHBORHOOD, {"side_effect_id": node_id}
        )
        if not rows:
            return GraphPayload(nodes=[], edges=[])
        se_node_id = f"side_effect:{node_id}"
        nodes[se_node_id] = GraphNode(
            id=se_node_id, label=rows[0]["se_name"], type="side_effect"
        )
        for row in rows:
            if row["rxcui"] is not None:
                drug_node_id = f"drug:{row['rxcui']}"
                nodes[drug_node_id] = GraphNode(
                    id=drug_node_id,
                    label=row["generic_name"],
                    type="drug",
                    drug_class=row["drug_class"],
                )
                edges.append(
                    GraphEdge(
                        source=drug_node_id,
                        target=se_node_id,
                        kind="has_side_effect",
                        report_count=row["report_count"],
                    )
                )

    return GraphPayload(nodes=list(nodes.values()), edges=edges)


def condition_subgraph(
    client: GraphExecutor,
    condition_id: str,
    per_med: int = 10,
) -> GraphPayload:
    name_rows = client.execute(CONDITION_NODE, {"condition_id": condition_id})
    drug_rows = client.execute(DRUGS_FOR_CONDITION, {"condition_id": condition_id})
    edge_rows = client.execute(
        TOP_SIDE_EFFECTS_PER_MED,
        {
            "condition_id": condition_id,
            "per_med": per_med,
        },
    )

    condition_node_id = f"condition:{condition_id}"
    nodes: dict[str, GraphNode] = {
        condition_node_id: GraphNode(
            id=condition_node_id,
            label=name_rows[0]["name"] if name_rows else condition_id,
            type="condition",
        )
    }
    edges: list[GraphEdge] = []

    for row in drug_rows:
        drug_node_id = f"drug:{row['rxcui']}"
        nodes[drug_node_id] = GraphNode(
            id=drug_node_id,
            label=row["generic_name"],
            type="drug",
            drug_class=row["drug_class"],
        )
        edges.append(
            GraphEdge(
                source=drug_node_id,
                target=condition_node_id,
                kind=row["rela"].lower(),
            )
        )

    for row in edge_rows:
        drug_node_id = f"drug:{row['rxcui']}"
        effect_node_id = f"side_effect:{row['side_effect_id']}"
        nodes[effect_node_id] = GraphNode(
            id=effect_node_id, label=row["side_effect_name"], type="side_effect"
        )
        edges.append(
            GraphEdge(
                source=drug_node_id,
                target=effect_node_id,
                kind="has_side_effect",
                report_count=row["report_count"],
            )
        )

    return GraphPayload(nodes=list(nodes.values()), edges=edges)
