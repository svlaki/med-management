import httpx
import pytest
import respx
from httpx import Response

from med_graph.models import Condition, Medication
from med_graph.sources.base import SourceFetchError
from med_graph.sources.conditions import ConditionSpec
from med_graph.sources.openfda_indication import (
    OPENFDA_LABEL_URL,
    OpenFdaIndicationSource,
    name_matches,
)

SPEC = ConditionSpec(
    condition=Condition(id="gad", name="Generalized Anxiety Disorder", icd10="F41.1"),
    rxclass_ids=("D001008",),
    label_indication_terms=("generalized anxiety disorder",),
)
MEDS = (
    Medication(rxcui="1", name="buspirone", generic_name="buspirone"),
    Medication(rxcui="2", name="lithium", generic_name="lithium"),
    Medication(rxcui="3", name="quetiapine", generic_name="quetiapine"),
)


def label_payload(*generic_names: str) -> dict:
    # Each synthetic label positively indicates the GAD term.
    return {
        "results": [
            {
                "openfda": {"generic_name": [g]},
                "indications_and_usage": [
                    "Indicated for the treatment of generalized anxiety disorder."
                ],
            }
            for g in generic_names
        ]
    }


def mock_indication(term: str, payload: dict, status: int = 200) -> None:
    respx.get(
        OPENFDA_LABEL_URL,
        params={"search": f'indications_and_usage:"{term}"'},
    ).mock(return_value=Response(status, json=payload))


def make() -> OpenFdaIndicationSource:
    return OpenFdaIndicationSource(retry_backoff_seconds=0)


class TestNameMatches:
    def test_ingredient_matches_within_brand_generic(self):
        assert name_matches("buspirone", {"buspirone hydrochloride"})

    def test_respects_word_boundaries(self):
        assert not name_matches("lith", {"lithium carbonate"})

    def test_no_match_when_absent(self):
        assert not name_matches("quetiapine", {"buspirone hydrochloride"})


@respx.mock
def test_approved_rxcuis_matches_by_generic_name():
    mock_indication(
        "generalized anxiety disorder",
        label_payload("BUSPIRONE HYDROCHLORIDE", "SERTRALINE"),
    )
    assert make().approved_rxcuis(SPEC, MEDS) == {"1"}


@respx.mock
def test_also_matches_substance_name():
    payload = {"results": [{"openfda": {"substance_name": ["QUETIAPINE FUMARATE"]}}]}
    mock_indication("generalized anxiety disorder", payload)
    assert make().approved_rxcuis(SPEC, MEDS) == {"3"}


@respx.mock
def test_no_approved_when_indication_has_no_labels():
    mock_indication("generalized anxiety disorder", {}, status=404)
    assert make().approved_rxcuis(SPEC, MEDS) == set()


@respx.mock
def test_http_error_raises_source_error():
    mock_indication("generalized anxiety disorder", {}, status=500)
    with pytest.raises(SourceFetchError, match="openfda"):
        make().approved_rxcuis(SPEC, MEDS)


def test_no_terms_means_nothing_approved():
    spec = ConditionSpec(
        condition=Condition(id="x", name="X", icd10=None),
        rxclass_ids=("D0",),
        label_indication_terms=(),
    )
    assert make().approved_rxcuis(spec, MEDS) == set()


def test_context_manager_closes_owned_client():
    with make() as source:
        http = source._http
    assert http.is_closed


def test_leaves_injected_client_open():
    injected = httpx.Client()
    with OpenFdaIndicationSource(http_client=injected):
        pass
    assert not injected.is_closed
    injected.close()
