"""Build a static, read-only snapshot of the whole graph as a plain dict.

The hosted frontend loads this JSON and does all filtering (per-medication
side-effect limits, label-confirmed filtering, reverse lookups) in the browser,
so the shared web app needs no database or API server.
"""

from datetime import datetime, timezone

from med_graph.graph.executor import GraphExecutor
from med_graph.queries.medications import (
    conditions_in_graph,
    medications_for_condition,
    side_effect_profile,
)

# Effectively "all" side effects for a medication (far above any real count).
ALL_SIDE_EFFECTS = 10_000

# Ids the frontend reserves for synthetic views (e.g. the merged "All
# conditions" option in api.ts). A real condition using one would be shadowed.
RESERVED_CONDITION_IDS = frozenset({"all"})


def build_snapshot(client: GraphExecutor) -> dict:
    graph_conditions = conditions_in_graph(client)
    collisions = RESERVED_CONDITION_IDS & {c["id"] for c in graph_conditions}
    if collisions:
        raise ValueError(
            f"Condition id(s) {sorted(collisions)} are reserved by the frontend; "
            "rename the condition before loading it."
        )

    conditions = []
    graphs: dict[str, dict] = {}

    for condition in graph_conditions:
        condition_id = condition["id"]
        conditions.append(
            {
                "id": condition_id,
                "name": condition["name"],
                "icd10": condition["icd10"],
            }
        )
        medications = []
        for med in medications_for_condition(client, condition_id):
            effects = side_effect_profile(client, med.rxcui, limit=ALL_SIDE_EFFECTS)
            medications.append(
                {
                    "rxcui": med.rxcui,
                    "generic_name": med.generic_name,
                    "drug_class": med.drug_class,
                    "fda_approved": med.fda_approved,
                    "atc_codes": med.atc_codes,
                    "mechanism": med.mechanism,
                    "neurotransmitters": med.neurotransmitters,
                    "side_effects": [
                        {
                            "side_effect_id": e.side_effect_id,
                            "name": e.name,
                            "source": e.source,
                            "report_count": e.report_count,
                            "label_confirmed": e.label_confirmed,
                        }
                        for e in effects
                    ],
                }
            )
        graphs[condition_id] = {"medications": medications}

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "conditions": conditions,
        "graphs": graphs,
    }
