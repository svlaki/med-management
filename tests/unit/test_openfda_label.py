import httpx
import pytest
import respx
from httpx import Response

from med_graph.models import CausesEdge, EdgeSource, Medication, SideEffect
from med_graph.sources.base import SourceBatch, SourceFetchError
from med_graph.sources.openfda_label import (
    OPENFDA_LABEL_URL,
    OpenFdaLabelSource,
    label_mentions,
)

NAUSEA = SideEffect(id="nausea", name="Nausea", meddra_term="NAUSEA")
INSOMNIA = SideEffect(id="insomnia", name="Insomnia", meddra_term="INSOMNIA")
WEIGHT = SideEffect(id="weight-increased", name="Weight increased",
                    meddra_term="WEIGHT INCREASED")

SERTRALINE = Medication(rxcui="36437", name="sertraline", generic_name="sertraline")
FLUOXETINE = Medication(rxcui="4493", name="fluoxetine", generic_name="fluoxetine")
BUPROPION = Medication(rxcui="42347", name="bupropion", generic_name="bupropion")


class TestLabelMentions:
    def test_matches_meddra_term_case_insensitively(self):
        assert label_mentions(NAUSEA, "Reactions included NAUSEA and vomiting.")
        assert label_mentions(NAUSEA, "reactions included nausea and vomiting.")

    def test_matches_multiword_term(self):
        assert label_mentions(WEIGHT, "Some patients had weight increased over time.")

    def test_respects_word_boundaries(self):
        # "fall" must not match inside "fallopian"
        fall = SideEffect(id="fall", name="Fall", meddra_term="FALL")
        assert not label_mentions(fall, "fallopian tube disorders were noted")
        assert label_mentions(fall, "risk of fall was elevated")

    def test_returns_false_for_absent_term(self):
        assert not label_mentions(INSOMNIA, "The most common reaction was nausea.")

    def test_returns_false_for_empty_text(self):
        assert not label_mentions(NAUSEA, "")


def mock_label(generic_name: str, reactions_text: str | None, status: int = 200):
    if reactions_text is None:
        payload = {"results": [{}]} if status == 200 else {}
    else:
        payload = {"results": [{"adverse_reactions": [reactions_text]}]}
    respx.get(
        OPENFDA_LABEL_URL,
        params={"search": f'openfda.generic_name:"{generic_name}"'},
    ).mock(return_value=Response(status, json=payload))


def make_source(**kwargs) -> OpenFdaLabelSource:
    kwargs.setdefault("request_delay_seconds", 0)
    kwargs.setdefault("retry_backoff_seconds", 0)
    return OpenFdaLabelSource(**kwargs)


BATCH = SourceBatch(
    side_effects=(NAUSEA, INSOMNIA),
    causes=(
        CausesEdge(medication_rxcui="36437", side_effect_id="nausea",
                   source=EdgeSource.FAERS, report_count=100),
        CausesEdge(medication_rxcui="4493", side_effect_id="insomnia",
                   source=EdgeSource.FAERS, report_count=80),
        CausesEdge(medication_rxcui="4493", side_effect_id="nausea",
                   source=EdgeSource.FAERS, report_count=60),
    ),
)


def confirmed_map(batch: SourceBatch) -> dict[tuple[str, str], bool | None]:
    return {
        (e.medication_rxcui, e.side_effect_id): e.label_confirmed for e in batch.causes
    }


@respx.mock
def test_confirm_sets_true_false_per_label_text():
    mock_label("sertraline", "Common reactions: nausea, headache.")
    mock_label("fluoxetine", "Common reactions: insomnia, anxiety.")

    result = make_source().confirm((SERTRALINE, FLUOXETINE), BATCH)

    flags = confirmed_map(result)
    assert flags[("36437", "nausea")] is True  # in sertraline label
    assert flags[("4493", "insomnia")] is True  # in fluoxetine label
    assert flags[("4493", "nausea")] is False  # fluoxetine label lacks nausea


@respx.mock
def test_confirm_treats_empty_adverse_reactions_as_unavailable():
    # A label exists but has no adverse-reactions section: nothing to check,
    # so effects are unknown (None), not denied (False).
    mock_label("sertraline", "")  # results[0].adverse_reactions == [""] -> joins to ""
    mock_label("fluoxetine", "insomnia")

    result = make_source().confirm((SERTRALINE, FLUOXETINE), BATCH)

    flags = confirmed_map(result)
    assert flags[("36437", "nausea")] is None


@respx.mock
def test_confirm_escapes_double_quote_in_generic_name():
    quoted = Medication(rxcui="999", name="x", generic_name='foo"bar')
    route = respx.get(
        OPENFDA_LABEL_URL,
        params={"search": 'openfda.generic_name:"foo\\"bar"'},
    ).mock(return_value=Response(200, json={"results": [{"adverse_reactions": ["x"]}]}))
    batch = SourceBatch(
        side_effects=(NAUSEA,),
        causes=(CausesEdge(medication_rxcui="999", side_effect_id="nausea",
                           source=EdgeSource.FAERS, report_count=1),),
    )

    make_source().confirm((quoted,), batch)

    assert route.called


@respx.mock
def test_confirm_leaves_none_when_no_label_available():
    # 404 => no label for this drug => cannot confirm or deny
    mock_label("sertraline", None, status=404)
    mock_label("fluoxetine", "Common reactions: insomnia, nausea.")

    result = make_source().confirm((SERTRALINE, FLUOXETINE), BATCH)

    flags = confirmed_map(result)
    assert flags[("36437", "nausea")] is None
    assert flags[("4493", "insomnia")] is True


@respx.mock
def test_confirm_preserves_side_effects_and_edge_count():
    mock_label("sertraline", "nausea")
    mock_label("fluoxetine", "insomnia")

    result = make_source().confirm((SERTRALINE, FLUOXETINE), BATCH)

    assert result.side_effects == BATCH.side_effects
    assert len(result.causes) == len(BATCH.causes)


@respx.mock
def test_confirm_fetches_each_generic_name_once():
    route_s = respx.get(
        OPENFDA_LABEL_URL, params={"search": 'openfda.generic_name:"sertraline"'}
    ).mock(return_value=Response(200, json={"results": [{"adverse_reactions": ["nausea"]}]}))
    respx.get(
        OPENFDA_LABEL_URL, params={"search": 'openfda.generic_name:"fluoxetine"'}
    ).mock(return_value=Response(200, json={"results": [{"adverse_reactions": ["insomnia"]}]}))

    make_source().confirm((SERTRALINE, FLUOXETINE), BATCH)

    assert route_s.call_count == 1


@respx.mock
def test_confirm_raises_on_http_error():
    mock_label("sertraline", None, status=500)
    mock_label("fluoxetine", "insomnia")

    with pytest.raises(SourceFetchError, match="openfda"):
        make_source().confirm((SERTRALINE, FLUOXETINE), BATCH)


def test_context_manager_closes_owned_client():
    with make_source() as source:
        http = source._http
    assert http.is_closed


def test_context_manager_leaves_injected_client_open():
    injected = httpx.Client()
    with OpenFdaLabelSource(http_client=injected, request_delay_seconds=0):
        pass
    assert not injected.is_closed
    injected.close()
