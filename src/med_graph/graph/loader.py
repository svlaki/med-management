"""
Idempotent graph loading: every write is MERGE-based so re-ingesting
the same source updates properties instead of duplicating nodes or edges.

Takes a GraphExecutor, a Condition, and a SourceBatch. Uses MERGE Cypher to:
  1. Merge the condition node
  2. Merge medication nodes
  3. Merge side effect nodes
  4. Merge TREATS edges
  5. Merge CAUSES edges

  Returns counts of each record type written.
"""

from med_graph.graph.executor import GraphExecutor
from med_graph.models import Condition
from med_graph.sources.base import SourceBatch

MERGE_CONDITION = """
MERGE (c:Condition {id: $id})
SET c.name = $name, c.icd10 = $icd10
"""

MERGE_MEDICATIONS = """
UNWIND $rows AS row
MERGE (m:Medication {rxcui: row.rxcui})
SET m.name = row.name, m.generic_name = row.generic_name, m.drug_class = row.drug_class
"""

MERGE_SIDE_EFFECTS = """
UNWIND $rows AS row
MERGE (s:SideEffect {id: row.id})
SET s.name = row.name, s.meddra_term = row.meddra_term
"""

MERGE_TREATS = """
UNWIND $rows AS row
MATCH (m:Medication {rxcui: row.medication_rxcui})
MATCH (c:Condition {id: row.condition_id})
MERGE (m)-[r:TREATS {source: row.source}]->(c)
SET r.approval_status = row.approval_status
"""

MERGE_CAUSES = """
UNWIND $rows AS row
MATCH (m:Medication {rxcui: row.medication_rxcui})
MATCH (s:SideEffect {id: row.side_effect_id})
MERGE (m)-[r:CAUSES {source: row.source}]->(s)
SET r.frequency = row.frequency, r.severity = row.severity,
    r.report_count = row.report_count, r.label_confirmed = row.label_confirmed
"""


def load_batch(
    client: GraphExecutor, condition: Condition, batch: SourceBatch
) -> dict[str, int]:
    """Upsert a source batch into the graph. Returns counts by record type."""
    client.execute(MERGE_CONDITION, condition.model_dump(mode="json"))

    for query, records in (
        (MERGE_MEDICATIONS, batch.medications),
        (MERGE_SIDE_EFFECTS, batch.side_effects),
        (MERGE_TREATS, batch.treats),
        (MERGE_CAUSES, batch.causes),
    ):
        if records:
            rows = [record.model_dump(mode="json") for record in records]
            client.execute(query, {"rows": rows})

    return {
        "medications": len(batch.medications),
        "side_effects": len(batch.side_effects),
        "treats": len(batch.treats),
        "causes": len(batch.causes),
    }
