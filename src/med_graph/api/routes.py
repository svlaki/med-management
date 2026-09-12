"""Read-only HTTP routes over the query layer."""

from fastapi import APIRouter, Depends, HTTPException, Query

from med_graph.api.dependencies import get_client
from med_graph.api.schemas import ApiResponse, ok
from med_graph.graph.executor import GraphExecutor
from med_graph.queries.graph import GraphPayload, condition_subgraph, node_neighborhood
from med_graph.queries.medications import (
    condition_exists,
    conditions_in_graph,
    drug_classes_in_graph,
    drug_conditions,
    drug_detail,
    medications_by_side_effect,
    medications_for_condition,
    search_index,
    side_effect_profile,
)
from med_graph.queries.results import (
    DrugCondition,
    DrugDetail,
    MedicationCause,
    MedicationSummary,
    SideEffectReport,
)

router = APIRouter()


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/conditions")
def list_conditions(
    client: GraphExecutor = Depends(get_client),
) -> ApiResponse[list[dict]]:
    return ok(conditions_in_graph(client))


@router.get("/drug-classes")
def list_drug_classes(
    client: GraphExecutor = Depends(get_client),
) -> ApiResponse[list[dict]]:
    return ok(drug_classes_in_graph(client))


@router.get("/conditions/{condition_id}/medications")
def condition_medications(
    condition_id: str, client: GraphExecutor = Depends(get_client)
) -> ApiResponse[list[MedicationSummary]]:
    return ok(medications_for_condition(client, condition_id))


@router.get("/conditions/{condition_id}/graph")
def condition_graph(
    condition_id: str,
    per_med: int = Query(10, ge=1, le=50),
    client: GraphExecutor = Depends(get_client),
) -> ApiResponse[GraphPayload]:
    if not condition_exists(client, condition_id):
        raise HTTPException(
            status_code=404, detail=f"Unknown condition '{condition_id}'"
        )
    payload = condition_subgraph(client, condition_id, per_med)
    return ok(payload)


@router.get("/medications/{rxcui}/side-effects")
def medication_side_effects(
    rxcui: str,
    limit: int = Query(20, ge=1, le=1000),
    client: GraphExecutor = Depends(get_client),
) -> ApiResponse[list[SideEffectReport]]:
    return ok(side_effect_profile(client, rxcui, limit))


@router.get("/side-effects/{side_effect_id}/medications")
def side_effect_medications(
    side_effect_id: str, client: GraphExecutor = Depends(get_client)
) -> ApiResponse[list[MedicationCause]]:
    return ok(medications_by_side_effect(client, side_effect_id))


@router.get("/drugs/{rxcui}/detail")
def get_drug_detail(
    rxcui: str, client: GraphExecutor = Depends(get_client)
) -> ApiResponse[DrugDetail | None]:
    return ok(drug_detail(client, rxcui))


@router.get("/drugs/{rxcui}/conditions")
def get_drug_conditions(
    rxcui: str, client: GraphExecutor = Depends(get_client)
) -> ApiResponse[list[DrugCondition]]:
    return ok(drug_conditions(client, rxcui))


@router.get("/nodes/{node_type}/{node_id}/neighborhood")
def get_node_neighborhood(
    node_type: str,
    node_id: str,
    per_med: int = Query(10, ge=1, le=50),
    client: GraphExecutor = Depends(get_client),
) -> ApiResponse[GraphPayload]:
    if node_type not in ("condition", "drug", "side_effect"):
        raise HTTPException(status_code=400, detail=f"Invalid node type '{node_type}'")
    payload = node_neighborhood(client, node_type, node_id, per_med)
    if not payload.nodes:
        raise HTTPException(status_code=404, detail=f"Node not found: {node_type}:{node_id}")
    return ok(payload)


@router.get("/search")
def get_search_index(
    client: GraphExecutor = Depends(get_client),
) -> ApiResponse[list[dict]]:
    return ok(search_index(client))
