import httpx
import pytest
import respx
from httpx import Response

from med_graph.sources.base import SourceFetchError
from med_graph.sources.rxclass_pharmacology import (
    BYRXCUI_URL,
    RxClassPharmacologySource,
    atc_to_class,
    parse_neurotransmitters,
)


class TestAtcToClass:
    def test_maps_common_psych_classes(self):
        assert atc_to_class(["N06AB"]) == "Antidepressant"
        assert atc_to_class(["N05AH"]) == "Antipsychotic"
        assert atc_to_class(["N05BA"]) == "Anxiolytic"
        assert atc_to_class(["N05CF"]) == "Sedative-Hypnotic"
        assert atc_to_class(["N06BA"]) == "Stimulant"
        assert atc_to_class(["N06DA"]) == "Anti-dementia"

    def test_lithium_is_mood_stabilizer_not_antipsychotic(self):
        # N05AN sits under N05A but is lithium — the more specific prefix wins
        assert atc_to_class(["N05AN01"]) == "Mood stabilizer"

    def test_antiepileptic_mood_stabilizer(self):
        assert atc_to_class(["N03AX"]) == "Mood stabilizer"

    def test_unknown_atc_falls_back_to_other(self):
        assert atc_to_class(["A02BC"]) == "Other"
        assert atc_to_class([]) == "Other"

    def test_picks_a_stable_primary_when_multiple(self):
        # antipsychotic outranks anxiolytic
        assert atc_to_class(["N05BA", "N05AH"]) == "Antipsychotic"


class TestParseNeurotransmitters:
    def test_extracts_name_and_direction(self):
        pe = [
            "Increased Central Nervous System Serotonin Activity",
            "Decreased Dopamine Activity",
        ]
        assert parse_neurotransmitters(pe) == [("Serotonin", "+"), ("Dopamine", "-")]

    def test_gaba_and_norepinephrine(self):
        pe = [
            "Increased Central Nervous System GABA Activity",
            "Increased Cerebral Cortex Norepinephrine Activity",
        ]
        assert parse_neurotransmitters(pe) == [
            ("Norepinephrine", "+"),
            ("GABA", "+"),
        ]

    def test_ignores_non_neurotransmitter_effects(self):
        assert parse_neurotransmitters(["Bronchodilation"]) == []

    def test_dedupes_and_is_deterministically_ordered(self):
        pe = ["Decreased Serotonin Activity", "Decreased Serotonin Activity"]
        assert parse_neurotransmitters(pe) == [("Serotonin", "-")]


def payload(atc=(), moa=(), pe=(), disease=()):
    info = []
    for cid, name in atc:
        info.append({"rxclassMinConceptItem": {"classId": cid, "className": name,
                     "classType": "ATC1-4"}, "relaSource": "ATC", "rela": ""})
    for name in moa:
        info.append({"rxclassMinConceptItem": {"classId": "M", "className": name,
                     "classType": "MOA"}, "relaSource": "MEDRT", "rela": "has_moa"})
    for name in pe:
        info.append({"rxclassMinConceptItem": {"classId": "P", "className": name,
                     "classType": "PE"}, "relaSource": "MEDRT", "rela": "has_pe"})
    for name in disease:
        info.append({"rxclassMinConceptItem": {"classId": "D", "className": name,
                     "classType": "DISEASE"}, "relaSource": "MEDRT", "rela": "may_treat"})
    return {"rxclassDrugInfoList": {"rxclassDrugInfo": info}}


def mock_byrxcui(rxcui, payload_dict, status=200):
    respx.get(BYRXCUI_URL, params={"rxcui": rxcui}).mock(
        return_value=Response(status, json=payload_dict)
    )


def make():
    return RxClassPharmacologySource(retry_backoff_seconds=0)


@respx.mock
def test_pharmacology_assembles_all_fields():
    mock_byrxcui("36437", payload(
        atc=[("N06AB", "Selective serotonin reuptake inhibitors")],
        moa=["Serotonin Uptake Inhibitors"],
        pe=["Increased Central Nervous System Serotonin Activity"],
        disease=["Depressive Disorder", "Obsessive-Compulsive Disorder"],
    ))
    result = make().pharmacology("36437")
    assert result["drug_class"] == "Antidepressant"
    assert result["atc_codes"] == ["N06AB"]
    assert result["mechanisms"] == ["Serotonin Uptake Inhibitors"]
    assert result["neurotransmitters"] == [("Serotonin", "+")]
    assert set(result["may_treat"]) == {"Depressive Disorder", "Obsessive-Compulsive Disorder"}


@respx.mock
def test_excludes_contraindicated_moa_and_disease():
    info = payload(atc=[("N06AB", "x")])["rxclassDrugInfoList"]["rxclassDrugInfo"]
    info.append({"rxclassMinConceptItem": {"classId": "M2", "className": "MAO Inhibitors",
                 "classType": "MOA"}, "relaSource": "MEDRT", "rela": "ci_moa"})
    info.append({"rxclassMinConceptItem": {"classId": "D2", "className": "Drug Hypersensitivity",
                 "classType": "DISEASE"}, "relaSource": "MEDRT", "rela": "ci_with"})
    mock_byrxcui("36437", {"rxclassDrugInfoList": {"rxclassDrugInfo": info}})
    result = make().pharmacology("36437")
    assert result["mechanisms"] == []           # ci_moa excluded
    assert result["may_treat"] == []            # ci_with excluded


@respx.mock
def test_missing_drug_returns_empty_pharmacology():
    mock_byrxcui("999", {}, status=404)
    result = make().pharmacology("999")
    assert result["drug_class"] == "Other"
    assert result["neurotransmitters"] == []


@respx.mock
def test_http_error_raises():
    mock_byrxcui("36437", {}, status=500)
    with pytest.raises(SourceFetchError, match="rxclass"):
        make().pharmacology("36437")


def test_context_manager_closes_owned_client():
    with make() as source:
        http = source._http
    assert http.is_closed
