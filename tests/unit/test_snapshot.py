import pytest

from med_graph.queries.medications import (
    CONDITIONS_IN_GRAPH,
    MEDS_FOR_CONDITION,
    SIDE_EFFECT_PROFILE,
)
from med_graph.snapshot import RESERVED_CONDITION_IDS, build_snapshot


class FakeExecutor:
    """Returns the graph's conditions, med rows per condition, and side effects."""

    def __init__(self, conditions=None):
        self.conditions = conditions or [
            {"id": "mdd", "name": "Major Depressive Disorder", "icd10": "F33"},
        ]
        self.meds = [
            {"rxcui": "36437", "generic_name": "sertraline", "drug_class": "Antidepressant",
             "side_effect_count": 2, "fda_approved": True, "atc_codes": "N06AB",
             "mechanism": "Serotonin Uptake Inhibitors",
             "neurotransmitters": "Serotonin(+)"},
        ]
        self.side_effects = [
            {"side_effect_id": "nausea", "name": "Nausea", "source": "faers",
             "report_count": 13644, "label_confirmed": True},
            {"side_effect_id": "insomnia", "name": "Insomnia", "source": "faers",
             "report_count": 500, "label_confirmed": False},
        ]

    def execute(self, query, parameters=None):
        if query == CONDITIONS_IN_GRAPH:
            return self.conditions
        if query == MEDS_FOR_CONDITION:
            return self.meds
        if query == SIDE_EFFECT_PROFILE:
            return self.side_effects
        return []


def test_snapshot_has_conditions_and_graphs():
    snapshot = build_snapshot(FakeExecutor())
    assert any(c["id"] == "mdd" for c in snapshot["conditions"])
    assert "mdd" in snapshot["graphs"]
    assert "generated_at" in snapshot


def test_snapshot_nests_full_side_effects_per_medication():
    snapshot = build_snapshot(FakeExecutor())
    meds = snapshot["graphs"]["mdd"]["medications"]
    assert meds[0]["rxcui"] == "36437"
    effects = meds[0]["side_effects"]
    assert {e["side_effect_id"] for e in effects} == {"nausea", "insomnia"}
    assert effects[0]["report_count"] == 13644
    assert effects[0]["label_confirmed"] is True


def test_snapshot_carries_pharmacology_fields():
    snapshot = build_snapshot(FakeExecutor())
    med = snapshot["graphs"]["mdd"]["medications"][0]
    assert med["drug_class"] == "Antidepressant"
    assert med["mechanism"] == "Serotonin Uptake Inhibitors"
    assert med["neurotransmitters"] == "Serotonin(+)"
    assert med["atc_codes"] == "N06AB"


def test_reserved_condition_ids_are_rejected():
    # A real condition id colliding with the frontend's merged-view sentinel
    # ("all") would shadow that condition; the exporter must refuse it.
    reserved = next(iter(RESERVED_CONDITION_IDS))
    executor = FakeExecutor(
        conditions=[{"id": reserved, "name": "Bad", "icd10": None}]
    )
    with pytest.raises(ValueError, match=reserved):
        build_snapshot(executor)


def test_snapshot_requests_all_side_effects_not_a_small_limit():
    class LimitCapturingExecutor(FakeExecutor):
        def __init__(self):
            super().__init__()
            self.profile_limits = []

        def execute(self, query, parameters=None):
            if query == SIDE_EFFECT_PROFILE:
                self.profile_limits.append((parameters or {}).get("limit"))
            return super().execute(query, parameters)

    client = LimitCapturingExecutor()
    build_snapshot(client)
    assert client.profile_limits and all(limit >= 1000 for limit in client.profile_limits)
