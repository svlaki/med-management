import csv
from pathlib import Path

import pytest

from med_graph.sources.dataset_csv import build_dataset_batches

DATASET_HEADER = [
    "rxcui", "generic_name", "drug_class", "atc_codes", "neurotransmitters",
    "mechanism", "fda_approved", "approved_for", "may_treat",
    "label_confirmed_side_effects", "faers_only_side_effects",
]


def _write_csv(path: Path, header, rows):
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


@pytest.fixture
def dataset(tmp_path):
    csv_path = tmp_path / "dataset.csv"
    faers_path = tmp_path / "raw_faers.csv"
    _write_csv(
        csv_path,
        DATASET_HEADER,
        [
            [
                "1", "sertraline", "Antidepressant", "N06AB", "Serotonin(+)",
                "Serotonin Uptake Inhibitors", "True",
                "Major Depressive Disorder", "OCD; Major Depressive Disorder",
                "Nausea; Diarrhoea", "Insomnia",
            ],
            [
                "2", "quetiapine", "Antipsychotic", "N05AH", "Dopamine(-)",
                "Dopamine Antagonists", "True",
                "Bipolar Disorder", "Major Depressive Disorder",
                "Nausea", "",
            ],
        ],
    )
    _write_csv(
        faers_path,
        ["rxcui", "generic_name", "reaction_term", "report_count"],
        [
            ["1", "sertraline", "NAUSEA", "13644"],
            ["1", "sertraline", "DIARRHOEA", "10168"],
            ["1", "sertraline", "INSOMNIA", "5000"],
            ["2", "quetiapine", "NAUSEA", "80"],
        ],
    )
    return build_dataset_batches(csv_path, faers_path)


def _by_condition(batches):
    return {condition.id: batch for condition, batch in batches}


def test_conditions_are_canonicalized_and_deduped(dataset):
    ids = {condition.id for condition, _ in dataset}
    # OCD maps to "ocd"; the two MDD labels collapse to one "mdd".
    assert ids == {"mdd", "ocd", "bipolar"}


def test_approved_beats_may_treat_for_same_condition(dataset):
    # sertraline is both approved_for and may_treat MDD; the approved edge wins.
    mdd = _by_condition(dataset)["mdd"]
    sertraline_edges = [e for e in mdd.treats if e.medication_rxcui == "1"]
    assert len(sertraline_edges) == 1
    assert sertraline_edges[0].fda_approved is True


def test_may_treat_edge_is_not_approved(dataset):
    ocd = _by_condition(dataset)["ocd"]
    assert ocd.treats[0].medication_rxcui == "1"
    assert ocd.treats[0].fda_approved is False


def test_side_effect_bucket_sets_label_confirmed(dataset):
    mdd = _by_condition(dataset)["mdd"]
    causes = {c.side_effect_id: c for c in mdd.causes if c.medication_rxcui == "1"}
    assert causes["nausea"].label_confirmed is True  # label_confirmed column
    assert causes["insomnia"].label_confirmed is False  # faers_only column


def test_report_counts_join_from_raw_faers(dataset):
    mdd = _by_condition(dataset)["mdd"]
    causes = {c.side_effect_id: c for c in mdd.causes if c.medication_rxcui == "1"}
    assert causes["nausea"].report_count == 13644
    assert causes["diarrhoea"].report_count == 10168  # British spelling still joins


def test_medication_carries_pharmacology(dataset):
    mdd = _by_condition(dataset)["mdd"]
    sertraline = next(m for m in mdd.medications if m.rxcui == "1")
    assert sertraline.drug_class == "Antidepressant"
    assert sertraline.neurotransmitters == "Serotonin(+)"
    assert sertraline.mechanism == "Serotonin Uptake Inhibitors"
    assert sertraline.atc_codes == "N06AB"


def test_missing_faers_count_is_none(tmp_path):
    csv_path = tmp_path / "d.csv"
    faers_path = tmp_path / "f.csv"
    _write_csv(
        csv_path,
        DATASET_HEADER,
        [["9", "drugx", "Other", "", "", "", "False", "", "Insomnia", "", "Rareevent"]],
    )
    _write_csv(faers_path, ["rxcui", "generic_name", "reaction_term", "report_count"], [])
    batches = build_dataset_batches(csv_path, faers_path)
    causes = _by_condition(batches)["insomnia"].causes
    assert causes[0].report_count is None
