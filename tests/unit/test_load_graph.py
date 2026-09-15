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
        assert {"Mania", "Catatonia", "Aggression"} <= vocab

    def test_aliased_names_are_not_disorders_in_their_own_right(self, load_graph):
        """"Depression" and "Anxiety" merge into their canonical disorder nodes."""
        vocab = load_graph.disorder_vocabulary(tree_frame([]))
        for name in load_graph.CONDITION_ALIASES:
            assert name not in vocab

    def test_non_psychiatric_indications_are_absent(self, load_graph):
        tree = tree_frame([
            ["D003866", "36437", "sertraline", "may_treat", "Depressive Disorder"],
        ])
        vocab = load_graph.disorder_vocabulary(tree)
        for name in ("Anemia", "Atrial Fibrillation", "Angina Pectoris", "Beriberi"):
            assert name not in vocab


class TestTherapeuticEdges:
    # "Anxiety Disorders" and "Depressive Disorder" are the alias targets, so they
    # must be in the vocabulary for an aliased row to survive the membership test.
    VOCAB = frozenset({"Schizophrenia", "Depressive Disorder", "Anxiety Disorders"})

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

    def test_informal_names_are_aliased_to_their_canonical_disorder(self, load_graph):
        """A drug listed under "Anxiety" lands on the "Anxiety Disorders" node."""
        master = master_frame([
            ["36437", "may_treat", "Anxiety"],
            ["704", "may_treat", "Depression"],
        ])
        edges = load_graph.therapeutic_edges(master, self.VOCAB)
        assert set(edges.condition_name) == {"Anxiety Disorders", "Depressive Disorder"}

    def test_a_drug_on_both_the_alias_and_its_target_is_not_duplicated(self, load_graph):
        """MERGE dedupes in Neo4j, but the pair should collapse to one node name."""
        master = master_frame([
            ["36437", "may_treat", "Anxiety; Anxiety Disorders"],
        ])
        edges = load_graph.therapeutic_edges(master, self.VOCAB)
        assert set(edges.condition_name) == {"Anxiety Disorders"}


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
                     "Depressive Disorder"):
            assert name in present, f"{name} should be a disorder node"

    def test_merged_names_do_not_survive_as_their_own_disorder(self, scoped, load_graph):
        """"Anxiety" and "Depression" are folded into their canonical nodes."""
        edges, _ = scoped
        present = set(edges.condition_name)
        for name, canonical in load_graph.CONDITION_ALIASES.items():
            assert name not in present, f"{name} should have merged into {canonical}"
            assert canonical in present

    def test_no_drug_is_left_without_a_disorder(self, scoped):
        # Drugs and disorders both derive from this edge set, so by construction
        # every drug in the graph has at least one disorder edge.
        edges, _ = scoped
        assert len(set(edges.rxcui)) > 0
        assert edges.groupby("rxcui").size().min() >= 1


class FakeClient:
    """Captures the rows a loader would send, so no Neo4j is needed."""

    def __init__(self):
        self.rows = []

    def execute(self, query, params):
        self.rows = params["rows"]


def drug_frame(rows):
    return pd.DataFrame(
        rows,
        columns=[
            "rxcui", "generic_name", "has_label", "product_type",
            "neurotransmitters", "mechanism",
        ],
    )


class TestDrugNodes:
    """Pharmacology columns from drug_master become Drug properties."""

    SERTRALINE = [
        "36437", "sertraline", True, "HUMAN PRESCRIPTION DRUG",
        "Serotonin(+)", "Serotonin Uptake Inhibitors",
    ]

    def test_pharmacology_is_carried_onto_the_node(self, load_graph):
        client = FakeClient()
        load_graph.load_drugs(client, drug_frame([self.SERTRALINE]))
        assert client.rows[0]["neurotransmitters"] == "Serotonin(+)"
        assert client.rows[0]["mechanism"] == "Serotonin Uptake Inhibitors"

    def test_the_cypher_sets_both_properties(self, load_graph):
        assert "d.neurotransmitters = row.neurotransmitters" in load_graph.MERGE_DRUGS
        assert "d.mechanism = row.mechanism" in load_graph.MERGE_DRUGS

    def test_a_drug_without_pharmacology_gets_an_empty_string(self, load_graph):
        """An empty CSV cell reads back as NaN, which Neo4j cannot store."""
        charcoal = ["272", "activated charcoal", True, "HUMAN OTC DRUG", float("nan"), None]
        client = FakeClient()
        load_graph.load_drugs(client, drug_frame([charcoal]))
        assert client.rows[0]["neurotransmitters"] == ""
        assert client.rows[0]["mechanism"] == ""

    def test_one_node_per_drug_not_per_row(self, load_graph):
        client = FakeClient()
        load_graph.load_drugs(client, drug_frame([self.SERTRALINE, self.SERTRALINE]))
        assert len(client.rows) == 1


class TestDestructiveGuard:
    """main() wipes the target with CLEAR_GRAPH, so a declined confirmation
    must stop before the data files are even read."""

    def test_declining_returns_nonzero_and_touches_nothing(
        self, load_graph, monkeypatch, capsys
    ):
        from med_graph.config import Aborted

        monkeypatch.setattr(
            load_graph, "load_target", lambda name: _remote_target()
        )

        def refuse(target, action, assume_yes=False):
            raise Aborted("declined")

        monkeypatch.setattr(load_graph, "confirm_destructive", refuse)
        monkeypatch.setattr(
            load_graph.GraphClient,
            "from_env",
            lambda: pytest.fail("connected despite a declined confirmation"),
        )
        assert load_graph.main([]) == 1
        assert "Error" in capsys.readouterr().err

    def test_an_unknown_target_is_reported_not_raised(self, load_graph, capsys):
        assert load_graph.main(["--env", "nope"]) == 1
        assert "Error" in capsys.readouterr().err


def _remote_target():
    from pathlib import Path

    from med_graph.config import Target

    return Target("aura", Path(".env.aura"), "neo4j+s://abc.databases.neo4j.io")
