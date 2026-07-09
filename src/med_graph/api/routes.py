"""Read-only HTTP routes over the query layer."""

from fastapi import APIRouter, Depends, HTTPException, Query

from med_graph.api.dependencies import get_client
from med_graph.api.schemas import ApiResponse, ok
from med_graph.graph.executor import GraphExecutor
from med_graph.queries.graph import GraphPayload, condition_subgraph
from med_graph.queries.medications import (
    medications_by_side_effect,
    medications_for_condition,
    side_effect_profile,
)
from med_graph.queries.results import (
    MedicationCause,
    MedicationSummary,
    SideEffectReport,
)
from med_graph.sources.conditions import CONDITION_REGISTRY

router = APIRouter()


def _require_condition(condition_id: str) -> None:
    if condition_id not in CONDITION_REGISTRY:
        raise HTTPException(
            status_code=404, detail=f"Unknown condition '{condition_id}'"
        )


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/conditions")
def list_conditions() -> ApiResponse[list[dict]]:
    data = [
        {"id": spec.condition.id, "name": spec.condition.name,
         "icd10": spec.condition.icd10}
        for spec in CONDITION_REGISTRY.values()
    ]
    return ok(data)


@router.get("/conditions/{condition_id}/medications")
def condition_medications(
    condition_id: str, client: GraphExecutor = Depends(get_client)
) -> ApiResponse[list[MedicationSummary]]:
    _require_condition(condition_id)
    return ok(medications_for_condition(client, condition_id))


@router.get("/conditions/{condition_id}/graph")
def condition_graph(
    condition_id: str,
    confirmed_only: bool = False,
    per_med: int = Query(10, ge=1, le=50),
    client: GraphExecutor = Depends(get_client),
) -> ApiResponse[GraphPayload]:
    _require_condition(condition_id)
    payload = condition_subgraph(client, condition_id, confirmed_only, per_med)
    return ok(payload)


@router.get("/medications/{rxcui}/side-effects")
def medication_side_effects(
    rxcui: str,
    confirmed_only: bool = False,
    limit: int = Query(20, ge=1, le=100),
    client: GraphExecutor = Depends(get_client),
) -> ApiResponse[list[SideEffectReport]]:
    return ok(side_effect_profile(client, rxcui, limit, confirmed_only))


@router.get("/side-effects/{side_effect_id}/medications")
def side_effect_medications(
    side_effect_id: str, client: GraphExecutor = Depends(get_client)
) -> ApiResponse[list[MedicationCause]]:
    return ok(medications_by_side_effect(client, side_effect_id))
