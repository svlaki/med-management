"""Tests for the psychiatric scoping in scripts/load_graph.py.

The script lives outside the package, so it is loaded by path.
"""

import importlib.util
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "load_graph.py"


@pytest.fixture(scope="module")
def load_graph():
    spec = importlib.util.spec_from_file_location("load_graph", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def tree_frame(rows):
    return pd.DataFrame(
        rows, columns=["class_id", "rxcui", "generic_name", "rela", "condition_name"]
    )


def master_frame(rows):
    return pd.DataFrame(rows, columns=["rxcui", "rela", "condition_name"])


class TestDisorderVocabulary:
    def test_every_tree_condition_counts_as_a_disorder(self, load_graph):
        tree = tree_frame([
            ["D003866", "36437", "sertraline", "may_treat", "Depressive Disorder"],
            ["D012559", "51272", "quetiapine", "may_treat", "Schizophrenia"],
        ])
        vocab = load_graph.disorder_vocabulary(tree)
        assert {"Depressive Disorder", "Schizophrenia"} <= vocab

    def test_symptom_level_terms_are_added(self, load_graph):
        vocab = load_graph.disorder_vocabulary(tree_frame([]))
        # MeSH files these outside "Mental Disorders", but they are psychiatric.
        assert {"Anxiety", "Depression", "Mania", "Catatonia"} <= vocab

    def test_non_psychiatric_indications_are_absent(self, load_graph):
        tree = tree_frame([
            ["D003866", "36437", "sertraline", "may_treat", "Depressive Disorder"],
        ])
        vocab = load_graph.disorder_vocabulary(tree)
        for name in ("Anemia", "Atrial Fibrillation", "Angina Pectoris", "Beriberi"):
            assert name not in vocab


class TestTherapeuticEdges:
    VOCAB = frozenset({"Schizophrenia", "Depressive Disorder", "Anxiety"})

    def test_semicolon_joined_conditions_are_expanded(self, load_graph):
        master = master_frame([
            ["51272", "may_treat", "Schizophrenia; Depressive Disorder"],
        ])
        edges = load_graph.therapeutic_edges(master, self.VOCAB)
        assert set(edges.condition_name) == {"Schizophrenia", "Depressive Disorder"}
        assert list(edges.rxcui) == ["51272", "51272"]

    def test_conditions_outside_the_vocabulary_are_dropped(self, load_graph):
        master = master_frame([
            ["36437", "may_treat", "Depressive Disorder; Anemia; Atrial Fibrillation"],
        ])
        edges = load_graph.therapeutic_edges(master, self.VOCAB)
        assert list(edges.condition_name) == ["Depressive Disorder"]

    def test_contraindications_are_excluded(self, load_graph):
        master = master_frame([
            ["703", "ci_with", "Schizophrenia"],
            ["36437", "may_treat", "Schizophrenia"],
        ])
        edges = load_graph.therapeutic_edges(master, self.VOCAB)
        assert list(edges.rxcui) == ["36437"]
        assert "ci_with" not in set(edges.rela)

    def test_may_prevent_is_kept(self, load_graph):
        master = master_frame([["42347", "may_prevent", "Depressive Disorder"]])
        edges = load_graph.therapeutic_edges(master, self.VOCAB)
        assert list(edges.rela) == ["may_prevent"]

    def test_blank_condition_cells_are_skipped(self, load_graph):
        master = master_frame([
            ["17381", "may_treat", None],
            ["36437", "may_treat", "Anxiety"],
        ])
        edges = load_graph.therapeutic_edges(master, self.VOCAB)
        assert list(edges.rxcui) == ["36437"]

    def test_empty_input_yields_an_empty_frame_with_columns(self, load_graph):
        edges = load_graph.therapeutic_edges(master_frame([]), self.VOCAB)
        assert len(edges) == 0
        assert list(edges.columns) == ["rxcui", "rela", "condition_name"]


class TestGraphShape:
    def test_only_therapeutic_relationships_are_loaded(self, load_graph):
        assert set(load_graph.EDGE_QUERIES) == {"may_treat", "may_prevent"}
        assert not hasattr(load_graph, "MERGE_CI_WITH")


@pytest.fixture(scope="module")
def scoped(load_graph):
    """The real dataset, run through the same scoping the loader applies."""
    tree_path = REPO / "data_clean" / "tree_drug_conditions.csv"
    master_path = REPO / "data_clean" / "drug_master.csv"
    if not (tree_path.exists() and master_path.exists()):
        pytest.skip("data_clean CSVs not present")
    tree = pd.read_csv(tree_path, dtype=str)
    master = pd.read_csv(master_path, dtype=str)
    edges = load_graph.therapeutic_edges(master, load_graph.disorder_vocabulary(tree))
    names = master.drop_duplicates("rxcui").set_index("rxcui").generic_name
    return edges, names


class TestRealDataset:
    """Guards against the shipped dataset drifting out of the expected shape."""

    def test_known_psychiatric_drugs_survive(self, scoped):
        edges, names = scoped
        kept = {names[r] for r in set(edges.rxcui) if r in names.index}
        for drug in ("sertraline", "quetiapine", "haloperidol", "diazepam"):
            assert drug in kept, f"{drug} should be in scope"

    def test_non_psychiatric_drugs_are_dropped(self, scoped):
        edges, names = scoped
        kept = set(edges.rxcui)
        for drug in ("amiodarone", "furosemide", "levonorgestrel", "somatropin"):
            matches = names[names == drug].index
            assert all(r not in kept for r in matches), f"{drug} should be dropped"

    def test_every_disorder_is_psychiatric(self, scoped):
        edges, _ = scoped
        for name in ("Anemia", "Atrial Fibrillation", "Angina Pectoris", "Glaucoma"):
            assert name not in set(edges.condition_name)

    def test_core_disorders_are_present(self, scoped):
        edges, _ = scoped
        present = set(edges.condition_name)
        for name in ("Schizophrenia", "Bipolar Disorder", "Anxiety Disorders",
                     "Depressive Disorder", "Anxiety", "Depression"):
            assert name in present, f"{name} should be a disorder node"

    def test_no_drug_is_left_without_a_disorder(self, scoped):
        # Drugs and disorders both derive from this edge set, so by construction
        # every drug in the graph has at least one disorder edge.
        edges, _ = scoped
        assert len(set(edges.rxcui)) > 0
        assert edges.groupby("rxcui").size().min() >= 1
