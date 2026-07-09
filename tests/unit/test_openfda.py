import json
from pathlib import Path

import httpx
import pytest
import respx
from httpx import Response

from med_graph.models import EdgeSource, Medication
from med_graph.sources.base import SourceFetchError
from med_graph.sources.openfda import OPENFDA_BASE_URL, OpenFdaFaersSource

FIXTURES = Path(__file__).parent.parent / "fixtures"

SERTRALINE = Medication(rxcui="36437", name="sertraline", generic_name="sertraline")
FLUOXETINE = Medication(rxcui="4493", name="fluoxetine", generic_name="fluoxetine")


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def mock_reactions(generic_name: str, payload: dict, status: int = 200) -> None:
    respx.get(
        f"{OPENFDA_BASE_URL}/event.json",
        params={
            "search": f'patient.drug.openfda.generic_name:"{generic_name}"',
            "count": "patient.reaction.reactionmeddrapt.exact",
        },
    ).mock(return_value=Response(status, json=payload))


def make_source(**kwargs) -> OpenFdaFaersSource:
    kwargs.setdefault("request_delay_seconds", 0)
    kwargs.setdefault("retry_backoff_seconds", 0)
    return OpenFdaFaersSource(**kwargs)


@respx.mock
def test_enrich_builds_side_effects_and_causes_edges():
    mock_reactions("sertraline", fixture("faers_sertraline.json"))

    batch = make_source().enrich((SERTRALINE,))

    effect_ids = {effect.id for effect in batch.side_effects}
    assert effect_ids == {"nausea", "diarrhoea", "suicidal-ideation"}
    nausea_edge = next(e for e in batch.causes if e.side_effect_id == "nausea")
    assert nausea_edge.medication_rxcui == "36437"
    assert nausea_edge.source == EdgeSource.FAERS
    assert nausea_edge.report_count == 13644


@respx.mock
def test_meddra_term_preserved_and_name_humanized():
    mock_reactions("sertraline", fixture("faers_sertraline.json"))

    batch = make_source().enrich((SERTRALINE,))

    ideation = next(e for e in batch.side_effects if e.id == "suicidal-ideation")
    assert ideation.meddra_term == "SUICIDAL IDEATION"
    assert ideation.name == "Suicidal ideation"


@respx.mock
def test_administrative_terms_are_filtered():
    mock_reactions("sertraline", fixture("faers_sertraline.json"))

    batch = make_source().enrich((SERTRALINE,))

    assert "drug-ineffective" not in {effect.id for effect in batch.side_effects}


@respx.mock
def test_shared_side_effects_dedupe_but_keep_per_drug_edges():
    mock_reactions("sertraline", fixture("faers_sertraline.json"))
    mock_reactions("fluoxetine", fixture("faers_fluoxetine.json"))

    batch = make_source().enrich((SERTRALINE, FLUOXETINE))

    # NAUSEA reported for both drugs: one node, two edges
    nausea_nodes = [e for e in batch.side_effects if e.id == "nausea"]
    nausea_edges = [e for e in batch.causes if e.side_effect_id == "nausea"]
    assert len(nausea_nodes) == 1
    assert len(nausea_edges) == 2


@respx.mock
def test_drug_with_no_faers_reports_is_skipped():
    mock_reactions(
        "sertraline",
        {"error": {"code": "NOT_FOUND", "message": "No matches found!"}},
        status=404,
    )

    batch = make_source().enrich((SERTRALINE,))

    assert batch.side_effects == ()
    assert batch.causes == ()


@respx.mock
def test_http_error_raises_source_error():
    mock_reactions("sertraline", {}, status=500)

    with pytest.raises(SourceFetchError, match="openfda"):
        make_source().enrich((SERTRALINE,))


@respx.mock
def test_malformed_payload_raises_source_error():
    mock_reactions("sertraline", {"results": [{"unexpected": "shape"}]})

    with pytest.raises(SourceFetchError, match="shape"):
        make_source().enrich((SERTRALINE,))


@respx.mock
def test_single_invalid_row_is_skipped_not_fatal():
    # An empty term slugifies to "" (invalid id); a count of 0 fails report_count>0.
    # Neither should discard the valid rows collected before or after them.
    payload = {
        "results": [
            {"term": "NAUSEA", "count": 500},
            {"term": "!!!", "count": 300},
            {"term": "HEADACHE", "count": 0},
            {"term": "INSOMNIA", "count": 200},
        ]
    }
    mock_reactions("sertraline", payload)

    batch = make_source().enrich((SERTRALINE,))

    assert {e.id for e in batch.side_effects} == {"nausea", "insomnia"}


@respx.mock
def test_double_quote_in_generic_name_is_escaped():
    name = 'foo"bar'
    med = Medication(rxcui="999", name="x", generic_name=name)
    route = respx.get(
        f"{OPENFDA_BASE_URL}/event.json",
        params={
            "search": 'patient.drug.openfda.generic_name:"foo\\"bar"',
            "count": "patient.reaction.reactionmeddrapt.exact",
        },
    ).mock(return_value=Response(200, json={"results": []}))

    make_source().enrich((med,))

    assert route.called


@respx.mock
def test_retries_on_rate_limit_then_succeeds():
    route = respx.get(
        f"{OPENFDA_BASE_URL}/event.json",
        params={
            "search": 'patient.drug.openfda.generic_name:"sertraline"',
            "count": "patient.reaction.reactionmeddrapt.exact",
        },
    )
    route.side_effect = [
        Response(429),
        Response(200, json=fixture("faers_sertraline.json")),
    ]

    batch = make_source(max_retries=2).enrich((SERTRALINE,))

    assert "nausea" in {e.id for e in batch.side_effects}


@respx.mock
def test_gives_up_after_max_retries_on_rate_limit():
    mock_reactions("sertraline", {}, status=429)

    with pytest.raises(SourceFetchError, match="openfda"):
        make_source(max_retries=2).enrich((SERTRALINE,))


@pytest.mark.parametrize("bad_top_n", [0, -1, 5000])
def test_rejects_out_of_range_top_n(bad_top_n):
    with pytest.raises(ValueError):
        OpenFdaFaersSource(top_n=bad_top_n, request_delay_seconds=0)


def test_rejects_negative_delay_and_retries():
    with pytest.raises(ValueError):
        OpenFdaFaersSource(request_delay_seconds=-1)
    with pytest.raises(ValueError):
        OpenFdaFaersSource(max_retries=-1, request_delay_seconds=0)


@respx.mock
def test_transport_error_raises_source_error():
    respx.get(f"{OPENFDA_BASE_URL}/event.json").mock(
        side_effect=httpx.ConnectError("no route to host")
    )

    with pytest.raises(SourceFetchError, match="openfda"):
        make_source().enrich((SERTRALINE,))


def test_context_manager_closes_owned_client():
    with make_source() as source:
        http = source._http
    assert http.is_closed


def test_context_manager_leaves_injected_client_open():
    injected = httpx.Client()
    with OpenFdaFaersSource(http_client=injected, request_delay_seconds=0):
        pass
    assert not injected.is_closed
    injected.close()
