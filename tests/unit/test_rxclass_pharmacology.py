import httpx
import pytest
import respx
from httpx import Response

from med_graph.sources.base import SourceFetchError
from med_graph.sources.rxclass_pharmacology import (
    BYRXCUI_URL,
    RxClassPharmacologySource,
    atc_to_class,
    neurotransmitter_effects,
    neurotransmitters_from_moa,
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

    def test_activity_alteration_is_unclear_direction(self):
        assert parse_neurotransmitters(["Serotonin Activity Alteration"]) == [
            ("Serotonin", "~")
        ]

    def test_resolves_a_transmitter_named_by_its_adjective(self):
        # 'norepinephrine' never appears — only the adrenergic system does.
        assert parse_neurotransmitters(["Increased Adrenergic Activity"]) == [
            ("Norepinephrine", "+")
        ]

    def test_epinephrine_alias_does_not_fire_inside_norepinephrine(self):
        assert parse_neurotransmitters(["Increased Norepinephrine Activity"]) == [
            ("Norepinephrine", "+")
        ]


class TestNeurotransmittersFromMoa:
    def test_uptake_inhibitor_increases(self):
        assert neurotransmitters_from_moa(["Serotonin Uptake Inhibitors"]) == [
            ("Serotonin", "+")
        ]

    def test_antagonist_decreases(self):
        assert neurotransmitters_from_moa(["Dopamine Antagonists"]) == [("Dopamine", "-")]

    def test_agonist_increases(self):
        assert neurotransmitters_from_moa(["Serotonin Receptor Agonists"]) == [
            ("Serotonin", "+")
        ]

    def test_maoi_raises_all_three_monoamines(self):
        assert neurotransmitters_from_moa(["Monoamine Oxidase Inhibitors"]) == [
            ("Serotonin", "+"),
            ("Dopamine", "+"),
            ("Norepinephrine", "+"),
        ]

    def test_alpha2_agonist_reduces_norepinephrine(self):
        # clonidine/guanfacine: an agonist that LOWERS norepinephrine release.
        assert neurotransmitters_from_moa(["Adrenergic alpha2-Agonists"]) == [
            ("Norepinephrine", "-")
        ]

    def test_cholinesterase_inhibitor_raises_acetylcholine(self):
        assert neurotransmitters_from_moa(["Acetylcholinesterase Inhibitors"]) == [
            ("Acetylcholine", "+")
        ]

    def test_ignores_directionless_mechanisms(self):
        assert neurotransmitters_from_moa(["Cytochrome P450 Substrates"]) == []

    def test_orexin_antagonist_reduces_orexin(self):
        # daridorexant/lemborexant/suvorexant — blocking orexin promotes sleep
        assert neurotransmitters_from_moa(["Orexin Receptor Antagonists"]) == [
            ("Orexin", "-")
        ]

    def test_opioid_system_is_tracked(self):
        assert neurotransmitters_from_moa(["Opioid Antagonists"]) == [("Opioid", "-")]

    def test_nmda_antagonist_maps_to_glutamate(self):
        # esketamine — NMDA is a glutamate receptor
        assert neurotransmitters_from_moa(["Noncompetitive NMDA Receptor Antagonists"]) == [
            ("Glutamate", "-")
        ]


class TestNeurotransmitterEffects:
    def test_moa_fills_what_pe_lacks(self):
        # amoxapine-like: no serotonin PE, but MoA names both transmitters.
        effects = neurotransmitter_effects(
            pe_names=[],
            moa_names=["Serotonin Uptake Inhibitors", "Norepinephrine Uptake Inhibitors"],
        )
        assert effects == [("Serotonin", "+"), ("Norepinephrine", "+")]

    def test_pe_wins_on_conflict(self):
        effects = neurotransmitter_effects(
            pe_names=["Decreased Dopamine Activity"],
            moa_names=["Dopamine Agonists"],  # MoA would say +
        )
        assert effects == [("Dopamine", "-")]


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
