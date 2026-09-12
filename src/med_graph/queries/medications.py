"""Read queries over the medication graph.

Every query is a static Cypher constant; all runtime values flow through
parameters. Functions return typed, immutable result rows.
"""

from med_graph.graph.executor import GraphExecutor
from med_graph.models.slug import slugify
from med_graph.queries.results import (
    DrugCondition,
    DrugDetail,
    MedicationCause,
    MedicationSummary,
    SideEffectReport,
)

SIDE_EFFECT_PROFILE = """
MATCH (d:Drug {rxcui: $rxcui})-[r:HAS_SIDE_EFFECT]->(s:SideEffect)
RETURN s.id AS side_effect_id, s.name AS name,
       r.report_count AS report_count
ORDER BY coalesce(r.report_count, 0) DESC, s.name
LIMIT $limit
"""

MEDS_FOR_CONDITION = """
MATCH (d:Drug)-[:MAY_TREAT]->(c:Condition {id: $condition_id})
OPTIONAL MATCH (d)-[:BELONGS_TO]->(dc:DrugClass)
OPTIONAL MATCH (d)-[:HAS_SIDE_EFFECT]->(s:SideEffect)
RETURN d.rxcui AS rxcui, d.generic_name AS generic_name,
       dc.name AS drug_class, count(DISTINCT s) AS side_effect_count
ORDER BY generic_name
"""

MEDS_WITHOUT_SIDE_EFFECT = """
MATCH (d:Drug)-[:MAY_TREAT]->(:Condition {id: $condition_id})
WHERE NOT EXISTS {
  MATCH (d)-[:HAS_SIDE_EFFECT]->(s:SideEffect)
  WHERE toLower(s.name) CONTAINS toLower($term)
     OR toLower(s.id) CONTAINS toLower($term)
}
OPTIONAL MATCH (d)-[:BELONGS_TO]->(dc:DrugClass)
OPTIONAL MATCH (d)-[:HAS_SIDE_EFFECT]->(effect:SideEffect)
RETURN d.rxcui AS rxcui, d.generic_name AS generic_name,
       dc.name AS drug_class, count(DISTINCT effect) AS side_effect_count
ORDER BY generic_name
"""

CONDITION_EXISTS = """
MATCH (c:Condition {id: $condition_id})
RETURN c.id AS id
LIMIT 1
"""

CONDITIONS_IN_GRAPH = """
MATCH (c:Condition)
RETURN c.id AS id, c.name AS name
ORDER BY c.name
"""

DRUG_CLASSES_IN_GRAPH = """
MATCH (dc:DrugClass)
RETURN dc.id AS id, dc.name AS name
ORDER BY dc.name
"""

MEDS_BY_SIDE_EFFECT = """
MATCH (d:Drug)-[r:HAS_SIDE_EFFECT]->(s:SideEffect)
WHERE toLower(s.id) = toLower($side_effect_id)
RETURN d.rxcui AS rxcui, d.generic_name AS generic_name,
       r.report_count AS report_count
ORDER BY coalesce(r.report_count, 0) DESC, generic_name
"""

DRUG_DETAIL = """
MATCH (d:Drug {rxcui: $rxcui})
OPTIONAL MATCH (d)-[:BELONGS_TO]->(dc:DrugClass)
RETURN d.rxcui AS rxcui, d.generic_name AS generic_name,
       dc.name AS drug_class, d.has_label AS has_label,
       d.product_type AS product_type
"""

DRUG_CONDITIONS = """
MATCH (d:Drug {rxcui: $rxcui})-[r:MAY_TREAT]->(c:Condition)
RETURN c.id AS condition_id, c.name AS name, 'may_treat' AS rela
UNION ALL
MATCH (d:Drug {rxcui: $rxcui})-[r:MAY_PREVENT]->(c:Condition)
RETURN c.id AS condition_id, c.name AS name, 'may_prevent' AS rela
"""

RESOLVE_RXCUI = """
MATCH (d:Drug)
WHERE toLower(d.generic_name) = toLower($name)
RETURN d.rxcui AS rxcui
LIMIT 1
"""

SEARCH_INDEX = """
MATCH (c:Condition)
RETURN 'condition' AS type, c.id AS id, c.name AS label
UNION ALL
MATCH (d:Drug)
OPTIONAL MATCH (d)-[:BELONGS_TO]->(dc:DrugClass)
RETURN 'drug' AS type, d.rxcui AS id, d.generic_name AS label
UNION ALL
MATCH (s:SideEffect)
RETURN 'side_effect' AS type, s.id AS id, s.name AS label
"""


def side_effect_profile(
    client: GraphExecutor, rxcui: str, limit: int = 20
) -> list[SideEffectReport]:
    rows = client.execute(SIDE_EFFECT_PROFILE, {"rxcui": rxcui, "limit": limit})
    return [SideEffectReport(**row) for row in rows]


def medications_for_condition(
    client: GraphExecutor, condition_id: str
) -> list[MedicationSummary]:
    rows = client.execute(MEDS_FOR_CONDITION, {"condition_id": condition_id})
    return [MedicationSummary(**row) for row in rows]


def medications_without_side_effect(
    client: GraphExecutor, condition_id: str, term: str
) -> list[MedicationSummary]:
    """Drugs treating a condition with no side effect matching `term`."""
    rows = client.execute(
        MEDS_WITHOUT_SIDE_EFFECT, {"condition_id": condition_id, "term": term}
    )
    return [MedicationSummary(**row) for row in rows]


def condition_exists(client: GraphExecutor, condition_id: str) -> bool:
    """Whether a Condition node with this id is in the graph."""
    return bool(client.execute(CONDITION_EXISTS, {"condition_id": condition_id}))


def conditions_in_graph(client: GraphExecutor) -> list[dict]:
    """Every Condition node in the graph as {id, name} dicts."""
    return client.execute(CONDITIONS_IN_GRAPH)


def drug_classes_in_graph(client: GraphExecutor) -> list[dict]:
    """Every DrugClass node in the graph."""
    return client.execute(DRUG_CLASSES_IN_GRAPH)


def medications_by_side_effect(
    client: GraphExecutor, side_effect_id: str
) -> list[MedicationCause]:
    rows = client.execute(
        MEDS_BY_SIDE_EFFECT, {"side_effect_id": slugify(side_effect_id)}
    )
    return [MedicationCause(**row) for row in rows]


def drug_detail(client: GraphExecutor, rxcui: str) -> DrugDetail | None:
    """Return a single drug's details, or None."""
    rows = client.execute(DRUG_DETAIL, {"rxcui": rxcui})
    return DrugDetail(**rows[0]) if rows else None


def drug_conditions(client: GraphExecutor, rxcui: str) -> list[DrugCondition]:
    """The psychiatric disorders a drug may treat or prevent."""
    rows = client.execute(DRUG_CONDITIONS, {"rxcui": rxcui})
    return [DrugCondition(**row) for row in rows]


def resolve_rxcui(client: GraphExecutor, name: str) -> str | None:
    rows = client.execute(RESOLVE_RXCUI, {"name": name})
    return rows[0]["rxcui"] if rows else None


def search_index(client: GraphExecutor) -> list[dict]:
    """All searchable nodes for autocomplete."""
    return client.execute(SEARCH_INDEX)
