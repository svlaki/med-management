"""Read queries over the medication graph.

Every query is a static Cypher constant; all runtime values flow through
parameters. Functions return typed, immutable result rows.
"""

from med_graph.graph.executor import GraphExecutor
from med_graph.models.slug import slugify
from med_graph.queries.results import (
    MedicationCause,
    MedicationSummary,
    SideEffectReport,
)

SIDE_EFFECT_PROFILE = """
MATCH (m:Medication {rxcui: $rxcui})-[r:CAUSES]->(s:SideEffect)
RETURN s.id AS side_effect_id, s.name AS name, r.source AS source,
       r.report_count AS report_count, r.label_confirmed AS label_confirmed
ORDER BY coalesce(r.report_count, 0) DESC, s.name
LIMIT $limit
"""

SIDE_EFFECT_PROFILE_CONFIRMED = """
MATCH (m:Medication {rxcui: $rxcui})-[r:CAUSES]->(s:SideEffect)
WHERE r.label_confirmed = true
RETURN s.id AS side_effect_id, s.name AS name, r.source AS source,
       r.report_count AS report_count, r.label_confirmed AS label_confirmed
ORDER BY coalesce(r.report_count, 0) DESC, s.name
LIMIT $limit
"""

MEDS_FOR_CONDITION = """
MATCH (m:Medication)-[t:TREATS]->(:Condition {id: $condition_id})
OPTIONAL MATCH (m)-[:CAUSES]->(s:SideEffect)
RETURN m.rxcui AS rxcui, m.generic_name AS generic_name,
       m.drug_class AS drug_class, count(DISTINCT s) AS side_effect_count,
       any(x IN collect(t.fda_approved) WHERE x) AS fda_approved
ORDER BY generic_name
"""

MEDS_WITHOUT_SIDE_EFFECT = """
MATCH (m:Medication)-[:TREATS]->(:Condition {id: $condition_id})
WHERE NOT EXISTS {
  MATCH (m)-[:CAUSES]->(s:SideEffect)
  WHERE toLower(s.name) CONTAINS toLower($term)
     OR toLower(s.id) CONTAINS toLower($term)
}
OPTIONAL MATCH (m)-[:CAUSES]->(effect:SideEffect)
RETURN m.rxcui AS rxcui, m.generic_name AS generic_name,
       m.drug_class AS drug_class, count(DISTINCT effect) AS side_effect_count
ORDER BY generic_name
"""

MEDS_BY_SIDE_EFFECT = """
MATCH (m:Medication)-[r:CAUSES]->(s:SideEffect)
WHERE toLower(s.id) = toLower($side_effect_id)
RETURN m.rxcui AS rxcui, m.generic_name AS generic_name,
       r.report_count AS report_count
ORDER BY coalesce(r.report_count, 0) DESC, generic_name
"""

RESOLVE_RXCUI = """
MATCH (m:Medication)
WHERE toLower(m.generic_name) = toLower($name)
RETURN m.rxcui AS rxcui
LIMIT 1
"""


def side_effect_profile(
    client: GraphExecutor, rxcui: str, limit: int = 20, confirmed_only: bool = False
) -> list[SideEffectReport]:
    query = SIDE_EFFECT_PROFILE_CONFIRMED if confirmed_only else SIDE_EFFECT_PROFILE
    rows = client.execute(query, {"rxcui": rxcui, "limit": limit})
    return [SideEffectReport(**row) for row in rows]


def medications_for_condition(
    client: GraphExecutor, condition_id: str
) -> list[MedicationSummary]:
    rows = client.execute(MEDS_FOR_CONDITION, {"condition_id": condition_id})
    return [MedicationSummary(**row) for row in rows]


def medications_without_side_effect(
    client: GraphExecutor, condition_id: str, term: str
) -> list[MedicationSummary]:
    rows = client.execute(
        MEDS_WITHOUT_SIDE_EFFECT, {"condition_id": condition_id, "term": term}
    )
    return [MedicationSummary(**row) for row in rows]


def medications_by_side_effect(
    client: GraphExecutor, side_effect_id: str
) -> list[MedicationCause]:
    # SideEffect ids are stored as slugs; normalize display-form input (e.g.
    # "Weight gain") so it matches the stored id ("weight-gain").
    rows = client.execute(
        MEDS_BY_SIDE_EFFECT, {"side_effect_id": slugify(side_effect_id)}
    )
    return [MedicationCause(**row) for row in rows]


def resolve_rxcui(client: GraphExecutor, name: str) -> str | None:
    rows = client.execute(RESOLVE_RXCUI, {"name": name})
    return rows[0]["rxcui"] if rows else None
