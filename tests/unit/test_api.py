import pytest
from fastapi.testclient import TestClient

from med_graph.api.app import create_app
from med_graph.api.dependencies import get_client


class FakeClient:
    """Returns canned rows per query substring so routes can be tested without Neo4j."""

    def __init__(self, responder):
        self._responder = responder
        self.calls = []

    def execute(self, query, parameters=None):
        self.calls.append((query, parameters or {}))
        return self._responder(query, parameters or {})


@pytest.fixture
def client_factory():
    def make(responder):
        app = create_app()
        app.dependency_overrides[get_client] = lambda: FakeClient(responder)
        # raise_server_exceptions=False so the catch-all 500 handler is exercised
        return TestClient(app, raise_server_exceptions=False)

    return make


def test_health_ok(client_factory):
    api = client_factory(lambda q, p: [])
    resp = api.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_routes_are_served_under_the_api_prefix(client_factory):
    # The Vite dev server proxies /api to this app; an unprefixed route would
    # be unreachable from the frontend.
    api = client_factory(lambda q, p: [])
    assert api.get("/health").status_code == 404
    assert api.get("/api/health").status_code == 200


def test_list_conditions_includes_mdd(client_factory):
    rows = [{"id": "mdd", "name": "Major Depressive Disorder"}]
    api = client_factory(lambda q, p: rows)
    resp = api.get("/api/conditions")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    ids = {c["id"] for c in body["data"]}
    assert "mdd" in ids


def test_list_drug_classes(client_factory):
    rows = [{"id": "ssri", "name": "SSRI"}]
    api = client_factory(lambda q, p: rows)
    resp = api.get("/api/drug-classes")
    assert resp.status_code == 200
    assert resp.json()["data"][0]["name"] == "SSRI"


def test_condition_medications(client_factory):
    rows = [
        {"rxcui": "36437", "generic_name": "sertraline", "drug_class": None,
         "side_effect_count": 12}
    ]
    api = client_factory(lambda q, p: rows)
    resp = api.get("/api/conditions/mdd/medications")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"][0]["generic_name"] == "sertraline"


def test_medication_side_effects_passes_limit(client_factory):
    captured = {}

    def responder(query, params):
        captured["params"] = params
        return [{"side_effect_id": "nausea", "name": "Nausea", "report_count": 13644}]

    api = client_factory(responder)
    resp = api.get("/api/medications/36437/side-effects?limit=5")
    assert resp.status_code == 200
    assert resp.json()["data"][0]["name"] == "Nausea"
    assert captured["params"]["limit"] == 5


def test_side_effect_medications(client_factory):
    rows = [{"rxcui": "4493", "generic_name": "fluoxetine", "report_count": 5470}]
    api = client_factory(lambda q, p: rows)
    resp = api.get("/api/side-effects/insomnia/medications")
    assert resp.status_code == 200
    assert resp.json()["data"][0]["generic_name"] == "fluoxetine"


def test_drug_detail(client_factory):
    rows = [
        {"rxcui": "36437", "generic_name": "sertraline", "drug_class": "SSRI",
         "has_label": True, "product_type": "HUMAN PRESCRIPTION DRUG"}
    ]
    api = client_factory(lambda q, p: rows)
    resp = api.get("/api/drugs/36437/detail")
    assert resp.status_code == 200
    assert resp.json()["data"]["drug_class"] == "SSRI"


def test_drug_detail_missing_returns_null_data(client_factory):
    api = client_factory(lambda q, p: [])
    resp = api.get("/api/drugs/00000/detail")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"] is None


def test_drug_conditions(client_factory):
    rows = [{"condition_id": "mdd", "name": "MDD", "rela": "may_treat"}]
    api = client_factory(lambda q, p: rows)
    resp = api.get("/api/drugs/36437/conditions")
    assert resp.status_code == 200
    assert resp.json()["data"][0]["rela"] == "may_treat"


def test_search_index(client_factory):
    rows = [{"type": "drug", "id": "36437", "label": "sertraline"}]
    api = client_factory(lambda q, p: rows)
    resp = api.get("/api/search")
    assert resp.status_code == 200
    assert resp.json()["data"][0]["label"] == "sertraline"


def test_unknown_condition_returns_404(client_factory):
    # No Condition node matches, so the graph route must 404 rather than return
    # a payload containing only a phantom condition node.
    api = client_factory(lambda q, p: [])
    resp = api.get("/api/conditions/not-a-condition/graph")
    assert resp.status_code == 404
    assert resp.json()["success"] is False


def test_invalid_limit_returns_422_in_envelope(client_factory):
    api = client_factory(lambda q, p: [])
    resp = api.get("/api/medications/36437/side-effects?limit=notanint")
    assert resp.status_code == 422
    body = resp.json()
    assert body["success"] is False
    assert body["error"]


def test_out_of_range_per_med_rejected(client_factory):
    api = client_factory(lambda q, p: [])
    too_big = api.get("/api/conditions/mdd/graph?per_med=9999999")
    negative = api.get("/api/conditions/mdd/graph?per_med=-5")
    assert too_big.status_code == 422
    assert negative.status_code == 422
    assert too_big.json()["success"] is False


def test_unexpected_error_returns_envelope_500(client_factory):
    def boom(query, params):
        raise RuntimeError("db exploded")

    api = client_factory(boom)
    resp = api.get("/api/conditions/mdd/medications")
    assert resp.status_code == 500
    body = resp.json()
    assert body["success"] is False
    assert body["error"]
    assert "exploded" not in body["error"]  # no internal detail leaked


def test_condition_graph_returns_nodes_and_edges(client_factory):
    def responder(query, params):
        if "LIMIT 1" in query:  # condition_exists
            return [{"id": "mdd"}]
        if "RETURN c.name AS name" in query:  # CONDITION_NODE
            return [{"name": "Major Depressive Disorder"}]
        if "type(r) AS rela" in query:  # DRUGS_FOR_CONDITION
            return [
                {"rxcui": "36437", "generic_name": "sertraline", "drug_class": "SSRI",
                 "rela": "MAY_TREAT"}
            ]
        return [  # TOP_SIDE_EFFECTS_PER_MED
            {"rxcui": "36437", "side_effect_id": "nausea",
             "side_effect_name": "Nausea", "report_count": 13644}
        ]

    api = client_factory(responder)
    resp = api.get("/api/conditions/mdd/graph")
    assert resp.status_code == 200
    data = resp.json()["data"]
    node_ids = {n["id"] for n in data["nodes"]}
    assert {"condition:mdd", "drug:36437", "side_effect:nausea"} <= node_ids
    assert any(e["kind"] == "may_treat" for e in data["edges"])
    assert any(e["kind"] == "has_side_effect" for e in data["edges"])
