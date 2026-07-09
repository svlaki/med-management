import pytest
from pydantic import ValidationError

from med_graph.models import (
    CausesEdge,
    Condition,
    EdgeSource,
    Frequency,
    Medication,
    SideEffect,
    TreatsEdge,
)


class TestCondition:
    def test_valid_condition(self):
        condition = Condition(id="mdd", name="Major Depressive Disorder", icd10="F33")
        assert condition.id == "mdd"
        assert condition.icd10 == "F33"

    def test_icd10_is_optional(self):
        condition = Condition(id="mdd", name="Major Depressive Disorder")
        assert condition.icd10 is None

    def test_rejects_empty_name(self):
        with pytest.raises(ValidationError):
            Condition(id="mdd", name="")

    def test_id_is_normalized_to_lowercase_slug(self):
        condition = Condition(id=" MDD ", name="Major Depressive Disorder")
        assert condition.id == "mdd"

    def test_is_immutable(self):
        condition = Condition(id="mdd", name="Major Depressive Disorder")
        with pytest.raises(ValidationError):
            condition.name = "Something Else"


class TestMedication:
    def test_valid_medication(self):
        med = Medication(
            rxcui="36437",
            name="Zoloft",
            generic_name="sertraline",
            drug_class="SSRI",
        )
        assert med.rxcui == "36437"

    def test_rejects_non_numeric_rxcui(self):
        with pytest.raises(ValidationError):
            Medication(rxcui="not-a-cui", name="Zoloft", generic_name="sertraline")

    def test_drug_class_is_optional(self):
        med = Medication(rxcui="36437", name="Zoloft", generic_name="sertraline")
        assert med.drug_class is None

    def test_is_immutable(self):
        med = Medication(rxcui="36437", name="Zoloft", generic_name="sertraline")
        with pytest.raises(ValidationError):
            med.name = "Prozac"


class TestSideEffect:
    def test_valid_side_effect(self):
        effect = SideEffect(id="nausea", name="Nausea", meddra_term="Nausea")
        assert effect.id == "nausea"

    def test_id_is_normalized_to_lowercase_slug(self):
        effect = SideEffect(id="Weight Gain", name="Weight Gain")
        assert effect.id == "weight-gain"

    def test_rejects_id_with_no_alphanumeric_content(self):
        with pytest.raises(ValidationError):
            SideEffect(id="!!!", name="Mystery Effect")


class TestTreatsEdge:
    def test_valid_edge(self):
        edge = TreatsEdge(
            medication_rxcui="36437",
            condition_id="mdd",
            source=EdgeSource.RXCLASS,
        )
        assert edge.source == EdgeSource.RXCLASS

    def test_condition_id_is_normalized_like_condition_nodes(self):
        edge = TreatsEdge(
            medication_rxcui="36437",
            condition_id="MDD",
            source=EdgeSource.RXCLASS,
        )
        assert edge.condition_id == "mdd"

    def test_requires_known_source(self):
        with pytest.raises(ValidationError):
            TreatsEdge(
                medication_rxcui="36437",
                condition_id="mdd",
                source="patients-like-me",
            )


class TestCausesEdge:
    def test_valid_edge(self):
        edge = CausesEdge(
            medication_rxcui="36437",
            side_effect_id="nausea",
            source=EdgeSource.OPENFDA_LABEL,
            frequency=Frequency.COMMON,
        )
        assert edge.frequency == Frequency.COMMON

    def test_frequency_defaults_to_unknown(self):
        edge = CausesEdge(
            medication_rxcui="36437",
            side_effect_id="nausea",
            source=EdgeSource.OPENFDA_LABEL,
        )
        assert edge.frequency == Frequency.UNKNOWN

    def test_report_count_defaults_to_none(self):
        edge = CausesEdge(
            medication_rxcui="36437",
            side_effect_id="nausea",
            source=EdgeSource.FAERS,
        )
        assert edge.report_count is None

    def test_report_count_must_be_positive(self):
        with pytest.raises(ValidationError):
            CausesEdge(
                medication_rxcui="36437",
                side_effect_id="nausea",
                source=EdgeSource.FAERS,
                report_count=-5,
            )

    def test_label_confirmed_defaults_to_none(self):
        edge = CausesEdge(
            medication_rxcui="36437",
            side_effect_id="nausea",
            source=EdgeSource.FAERS,
        )
        assert edge.label_confirmed is None

    def test_label_confirmed_accepts_bool(self):
        edge = CausesEdge(
            medication_rxcui="36437",
            side_effect_id="nausea",
            source=EdgeSource.FAERS,
            label_confirmed=True,
        )
        assert edge.label_confirmed is True
