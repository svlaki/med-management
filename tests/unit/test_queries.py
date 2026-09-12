import pytest

from med_graph.queries.medications import (
    DRUG_CONDITIONS,
    DRUG_DETAIL,
    MEDS_BY_SIDE_EFFECT,
    MEDS_FOR_CONDITION,
    MEDS_WITHOUT_SIDE_EFFECT,
    RESOLVE_RXCUI,
    SIDE_EFFECT_PROFILE,
    conditions_in_graph,
    drug_classes_in_graph,
    drug_conditions,
    drug_detail,
    medications_by_side_effect,
    medications_for_condition,
    medications_without_side_effect,
    resolve_rxcui,
    search_index,
    side_effect_profile,
)
from med_graph.queries.results import (
    DrugCondition,
    DrugDetail,
    MedicationCause,
    MedicationSummary,
    SideEffectReport,
)

# Every query that takes runtime values. The unparameterized index queries
# (CONDITIONS_IN_GRAPH, DRUG_CLASSES_IN_GRAPH, SEARCH_INDEX) are excluded
# because they have nothing to parameterize.
ALL_QUERIES = (
    SIDE_EFFECT_PROFILE,
    MEDS_FOR_CONDITION,
    MEDS_WITHOUT_SIDE_EFFECT,
    MEDS_BY_SIDE_EFFECT,
    DRUG_DETAIL,
    DRUG_CONDITIONS,
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


def test_queries_target_the_drug_schema_not_the_legacy_medication_schema():
    # The graph was migrated to Drug/HAS_SIDE_EFFECT/MAY_TREAT; a query still
    # written against (m:Medication)-[:CAUSES] would silently return nothing.
    for query in ALL_QUERIES:
        assert ":Medication" not in query
        assert ":CAUSES" not in query
        assert ":TREATS" not in query


class TestSideEffectProfile:
    def test_parses_reports_and_passes_params(self):
        client = FakeExecutor(
            rows=[{"side_effect_id": "nausea", "name": "Nausea", "report_count": 13644}]
        )

        reports = side_effect_profile(client, "36437", limit=5)

        assert reports == [
            SideEffectReport(
                side_effect_id="nausea", name="Nausea", report_count=13644
            )
        ]
        (_, params) = client.calls[0]
        assert params == {"rxcui": "36437", "limit": 5}

    def test_orders_by_report_count_descending(self):
        assert "ORDER BY" in SIDE_EFFECT_PROFILE
        assert "DESC" in SIDE_EFFECT_PROFILE

    def test_default_limit_is_applied(self):
        client = FakeExecutor(rows=[])
        side_effect_profile(client, "36437")
        assert client.calls[0][1] == {"rxcui": "36437", "limit": 20}

    def test_missing_report_count_is_tolerated(self):
        client = FakeExecutor(
            rows=[{"side_effect_id": "rash", "name": "Rash", "report_count": None}]
        )
        assert side_effect_profile(client, "36437")[0].report_count is None


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

    def test_excludes_via_not_exists_subquery(self):
        assert "NOT EXISTS" in MEDS_WITHOUT_SIDE_EFFECT


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


class TestDrugDetail:
    def test_parses_detail_row(self):
        client = FakeExecutor(
            rows=[
                {
                    "rxcui": "36437",
                    "generic_name": "sertraline",
                    "drug_class": "Antidepressant",
                    "has_label": True,
                    "product_type": "HUMAN PRESCRIPTION DRUG",
                }
            ]
        )

        detail = drug_detail(client, "36437")

        assert detail == DrugDetail(
            rxcui="36437",
            generic_name="sertraline",
            drug_class="Antidepressant",
            has_label=True,
            product_type="HUMAN PRESCRIPTION DRUG",
        )
        assert client.calls[0][1] == {"rxcui": "36437"}

    def test_returns_none_when_absent(self):
        assert drug_detail(FakeExecutor(rows=[]), "nope") is None


class TestDrugConditions:
    def test_parses_all_relationship_kinds(self):
        client = FakeExecutor(
            rows=[
                {"condition_id": "mdd", "name": "MDD", "rela": "may_treat"},
                {"condition_id": "sad", "name": "SAD", "rela": "may_prevent"},
            ]
        )

        conditions = drug_conditions(client, "36437")

        assert conditions == [
            DrugCondition(condition_id="mdd", name="MDD", rela="may_treat"),
            DrugCondition(condition_id="sad", name="SAD", rela="may_prevent"),
        ]

    def test_query_unions_the_therapeutic_edge_types(self):
        for rela in ("MAY_TREAT", "MAY_PREVENT"):
            assert rela in DRUG_CONDITIONS

    def test_contraindications_are_not_part_of_the_graph(self):
        assert "CI_WITH" not in DRUG_CONDITIONS


class TestIndexQueries:
    def test_conditions_in_graph_passes_rows_through(self):
        rows = [{"id": "mdd", "name": "Major Depressive Disorder"}]
        assert conditions_in_graph(FakeExecutor(rows=rows)) == rows

    def test_drug_classes_in_graph_passes_rows_through(self):
        rows = [{"id": "ssri", "name": "SSRI"}]
        assert drug_classes_in_graph(FakeExecutor(rows=rows)) == rows

    def test_search_index_passes_rows_through(self):
        rows = [{"type": "drug", "id": "36437", "label": "sertraline"}]
        assert search_index(FakeExecutor(rows=rows)) == rows


class TestResolveRxcui:
    def test_returns_rxcui_when_found(self):
        client = FakeExecutor(rows=[{"rxcui": "36437"}])
        assert resolve_rxcui(client, "Sertraline") == "36437"
        assert client.calls[0][1] == {"name": "Sertraline"}

    def test_returns_none_when_not_found(self):
        client = FakeExecutor(rows=[])
        assert resolve_rxcui(client, "nonexistent") is None
