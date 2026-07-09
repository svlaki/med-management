import json
from pathlib import Path

import httpx
import pytest
import respx
from httpx import Response

from med_graph.models import EdgeSource
from med_graph.sources.base import SourceFetchError
from med_graph.sources.conditions import CONDITION_REGISTRY
from med_graph.sources.rxclass import RXCLASS_BASE_URL, RxClassSource

FIXTURES = Path(__file__).parent.parent / "fixtures"
MDD = CONDITION_REGISTRY["mdd"]


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def mock_class_members(class_id: str, payload: dict) -> None:
    # Full param set: these four define the contract with RxNav
    # (MED-RT may_treat relations at ingredient level).
    respx.get(
        f"{RXCLASS_BASE_URL}/classMembers.json",
        params={
            "classId": class_id,
            "relaSource": "MEDRT",
            "rela": "may_treat",
            "ttys": "IN",
        },
    ).mock(return_value=Response(200, json=payload))


@respx.mock
def test_fetch_parses_medications_and_treats_edges():
    mock_class_members("D003865", fixture("rxclass_members_d003865.json"))
    mock_class_members("D003866", fixture("rxclass_members_d003866.json"))

    batch = RxClassSource().fetch(MDD)

    rxcuis = {med.rxcui for med in batch.medications}
    assert rxcuis == {"1040028", "321988", "4493", "36437", "704"}
    fluoxetine = next(m for m in batch.medications if m.rxcui == "4493")
    assert fluoxetine.generic_name == "fluoxetine"


@respx.mock
def test_fetch_dedupes_across_classes():
    mock_class_members("D003865", fixture("rxclass_members_d003865.json"))
    mock_class_members("D003866", fixture("rxclass_members_d003866.json"))

    batch = RxClassSource().fetch(MDD)

    # fluoxetine appears in both classes but must yield one node and one edge
    assert len(batch.medications) == 5
    assert len(batch.treats) == 5


@respx.mock
def test_treats_edges_carry_provenance_and_condition():
    mock_class_members("D003865", fixture("rxclass_members_d003865.json"))
    mock_class_members("D003866", fixture("rxclass_members_d003866.json"))

    batch = RxClassSource().fetch(MDD)

    assert all(edge.source == EdgeSource.RXCLASS for edge in batch.treats)
    assert all(edge.condition_id == "mdd" for edge in batch.treats)


@respx.mock
def test_fetch_handles_empty_class():
    mock_class_members("D003865", {})
    mock_class_members("D003866", {})

    batch = RxClassSource().fetch(MDD)

    assert batch.medications == ()
    assert batch.treats == ()


@respx.mock
def test_fetch_raises_on_http_error():
    respx.get(f"{RXCLASS_BASE_URL}/classMembers.json").mock(
        return_value=Response(500)
    )

    with pytest.raises(SourceFetchError, match="rxclass"):
        RxClassSource().fetch(MDD)


@respx.mock
def test_fetch_raises_source_error_on_malformed_payload():
    payload = {"drugMemberGroup": {"drugMember": [{"unexpected": "shape"}]}}
    mock_class_members("D003865", payload)
    mock_class_members("D003866", {})

    with pytest.raises(SourceFetchError, match="shape"):
        RxClassSource().fetch(MDD)


@respx.mock
def test_fetch_handles_single_member_collapsed_to_object():
    # RxNav JSON is XML-derived and can collapse one-element arrays to a bare object
    payload = {
        "drugMemberGroup": {
            "drugMember": {
                "minConcept": {"rxcui": "36437", "name": "sertraline", "tty": "IN"}
            }
        }
    }
    mock_class_members("D003865", payload)
    mock_class_members("D003866", {})

    batch = RxClassSource().fetch(MDD)

    assert [med.rxcui for med in batch.medications] == ["36437"]


def test_context_manager_closes_owned_client():
    with RxClassSource() as source:
        http = source._http
    assert http.is_closed


def test_context_manager_leaves_injected_client_open():
    injected = httpx.Client()
    with RxClassSource(http_client=injected):
        pass
    assert not injected.is_closed
    injected.close()
