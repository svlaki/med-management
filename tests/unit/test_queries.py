import pytest

from med_graph.queries.medications import (
    MEDS_BY_SIDE_EFFECT,
    MEDS_FOR_CONDITION,
    MEDS_WITHOUT_SIDE_EFFECT,
    RESOLVE_RXCUI,
    SIDE_EFFECT_PROFILE,
    SIDE_EFFECT_PROFILE_CONFIRMED,
    medications_by_side_effect,
    medications_for_condition,
    medications_without_side_effect,
    resolve_rxcui,
    side_effect_profile,
)
from med_graph.queries.results import (
    MedicationCause,
    MedicationSummary,
    SideEffectReport,
)

ALL_QUERIES = (
    SIDE_EFFECT_PROFILE,
    SIDE_EFFECT_PROFILE_CONFIRMED,
    MEDS_FOR_CONDITION,
    MEDS_WITHOUT_SIDE_EFFECT,
    MEDS_BY_SIDE_EFFECT,
    RESOLVE_RXCUI,
)


class FakeExecutor:
    """Records queries/params and returns canned rows."""

    def __init__(self, rows=None):
        self.rows = rows or []
        self.calls = []

    def execute(self, query, parameters=None):
        self.calls.append((query, parameters or {}))
        return self.rows


def test_all_queries_are_parameterized_not_interpolated():
    # No query string should contain Python f-string or % interpolation markers.
    for query in ALL_QUERIES:
        assert "{}" not in query
        assert "%s" not in query
        assert "$" in query  # uses Cypher parameters


class TestSideEffectProfile:
    def test_parses_reports_and_passes_params(self):
        client = FakeExecutor(
            rows=[
                {
                    "side_effect_id": "nausea",
                    "name": "Nausea",
                    "source": "faers",
                    "report_count": 13644,
                }
            ]
        )

        reports = side_effect_profile(client, "36437", limit=5)

        assert reports == [
            SideEffectReport(
                side_effect_id="nausea",
                name="Nausea",
                source="faers",
                report_count=13644,
            )
        ]
        (_, params) = client.calls[0]
        assert params == {"rxcui": "36437", "limit": 5}

    def test_orders_by_report_count_descending(self):
        assert "ORDER BY" in SIDE_EFFECT_PROFILE
        assert "DESC" in SIDE_EFFECT_PROFILE

    def test_confirmed_only_selects_label_filtered_query(self):
        client = FakeExecutor(rows=[])
        side_effect_profile(client, "36437", confirmed_only=True)
        assert client.calls[0][0] == SIDE_EFFECT_PROFILE_CONFIRMED

    def test_default_selects_unfiltered_query(self):
        client = FakeExecutor(rows=[])
        side_effect_profile(client, "36437")
        assert client.calls[0][0] == SIDE_EFFECT_PROFILE

    def test_confirmed_query_filters_on_label_confirmed(self):
        assert "label_confirmed = true" in SIDE_EFFECT_PROFILE_CONFIRMED

    def test_parses_label_confirmed_field(self):
        client = FakeExecutor(
            rows=[
                {
                    "side_effect_id": "nausea",
                    "name": "Nausea",
                    "source": "faers",
                    "report_count": 100,
                    "label_confirmed": True,
                }
            ]
        )
        reports = side_effect_profile(client, "36437")
        assert reports[0].label_confirmed is True


class TestMedicationsForCondition:
    def test_parses_summaries(self):
        client = FakeExecutor(
            rows=[
                {
                    "rxcui": "36437",
                    "generic_name": "sertraline",
                    "drug_class": None,
                    "side_effect_count": 12,
                }
            ]
        )

        meds = medications_for_condition(client, "mdd")

        assert meds == [
            MedicationSummary(
                rxcui="36437",
                generic_name="sertraline",
                drug_class=None,
                side_effect_count=12,
            )
        ]
        assert client.calls[0][1] == {"condition_id": "mdd"}


class TestMedicationsWithoutSideEffect:
    def test_passes_condition_and_term(self):
        client = FakeExecutor(rows=[])

        medications_without_side_effect(client, "mdd", "weight")

        assert client.calls[0][1] == {"condition_id": "mdd", "term": "weight"}

    def test_term_match_is_case_insensitive_in_query(self):
        assert "toLower" in MEDS_WITHOUT_SIDE_EFFECT


class TestMedicationsBySideEffect:
    def test_parses_causes_ranked(self):
        client = FakeExecutor(
            rows=[
                {"rxcui": "36437", "generic_name": "sertraline", "report_count": 7420}
            ]
        )

        causes = medications_by_side_effect(client, "insomnia")

        assert causes == [
            MedicationCause(
                rxcui="36437", generic_name="sertraline", report_count=7420
            )
        ]
        assert client.calls[0][1] == {"side_effect_id": "insomnia"}

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("Weight gain", "weight-gain"),
            ("Weight-Gain", "weight-gain"),
            ("INSOMNIA", "insomnia"),
        ],
    )
    def test_display_form_term_is_slugified_to_match_stored_ids(self, raw, expected):
        # SideEffect ids are stored as slugs; the query does an exact id match,
        # so a display-form argument must be normalized before querying.
        client = FakeExecutor(rows=[])

        medications_by_side_effect(client, raw)

        assert client.calls[0][1] == {"side_effect_id": expected}


class TestResolveRxcui:
    def test_returns_rxcui_when_found(self):
        client = FakeExecutor(rows=[{"rxcui": "36437"}])
        assert resolve_rxcui(client, "Sertraline") == "36437"
        assert client.calls[0][1] == {"name": "Sertraline"}

    def test_returns_none_when_not_found(self):
        client = FakeExecutor(rows=[])
        assert resolve_rxcui(client, "nonexistent") is None
