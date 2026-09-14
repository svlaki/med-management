"""Tests for the pharmacology join in scripts/merge_pharmacology.py.

The script lives outside the package, so it is loaded by path.
"""

import importlib.util
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "merge_pharmacology.py"


@pytest.fixture(scope="module")
def merge_pharmacology():
    spec = importlib.util.spec_from_file_location("merge_pharmacology", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def master_frame(rows):
    """drug_master is long-format: one row per drug/rela pair."""
    return pd.DataFrame(rows, columns=["rxcui", "generic_name", "rela"])


def psych_frame(rows):
    return pd.DataFrame(rows, columns=["rxcui", "neurotransmitters", "mechanism"])


AMITRIPTYLINE = ["704", "Serotonin(-); Norepinephrine(+)", "Serotonin Uptake Inhibitors"]


class TestAddPharmacology:
    def test_a_drugs_pharmacology_repeats_across_all_of_its_rows(self, merge_pharmacology):
        master = master_frame([
            ["704", "amitriptyline", "may_treat"],
            ["704", "amitriptyline", "ci_with"],
        ])
        merged = merge_pharmacology.add_pharmacology(master, psych_frame([AMITRIPTYLINE]))
        assert list(merged.neurotransmitters) == [AMITRIPTYLINE[1]] * 2
        assert list(merged.mechanism) == [AMITRIPTYLINE[2]] * 2

    def test_row_count_is_preserved(self, merge_pharmacology):
        master = master_frame([
            ["704", "amitriptyline", "may_treat"],
            ["704", "amitriptyline", "ci_with"],
            ["272", "activated charcoal", "may_treat"],
        ])
        merged = merge_pharmacology.add_pharmacology(master, psych_frame([AMITRIPTYLINE]))
        assert len(merged) == len(master)

    def test_drugs_outside_the_psychiatric_dataset_get_an_empty_string(self, merge_pharmacology):
        master = master_frame([
            ["704", "amitriptyline", "may_treat"],
            ["272", "activated charcoal", "may_treat"],
        ])
        merged = merge_pharmacology.add_pharmacology(master, psych_frame([AMITRIPTYLINE]))
        charcoal = merged[merged.rxcui == "272"].iloc[0]
        assert charcoal.neurotransmitters == ""
        assert charcoal.mechanism == ""

    def test_a_blank_source_cell_becomes_an_empty_string(self, merge_pharmacology):
        """gabapentin has a mechanism but no tracked neurotransmitter."""
        master = master_frame([["25480", "gabapentin", "may_treat"]])
        psych = psych_frame([["25480", None, "Unknown Cellular or Molecular Interaction"]])
        merged = merge_pharmacology.add_pharmacology(master, psych)
        assert merged.neurotransmitters.iloc[0] == ""
        assert merged.mechanism.iloc[0] == "Unknown Cellular or Molecular Interaction"

    def test_columns_are_appended_in_order(self, merge_pharmacology):
        master = master_frame([["704", "amitriptyline", "may_treat"]])
        merged = merge_pharmacology.add_pharmacology(master, psych_frame([AMITRIPTYLINE]))
        assert list(merged.columns)[-2:] == ["neurotransmitters", "mechanism"]

    def test_the_input_frame_is_not_mutated(self, merge_pharmacology):
        master = master_frame([["704", "amitriptyline", "may_treat"]])
        before = list(master.columns)
        merge_pharmacology.add_pharmacology(master, psych_frame([AMITRIPTYLINE]))
        assert list(master.columns) == before

    def test_rerunning_overwrites_rather_than_duplicating(self, merge_pharmacology):
        master = master_frame([["704", "amitriptyline", "may_treat"]])
        psych = psych_frame([AMITRIPTYLINE])
        once = merge_pharmacology.add_pharmacology(master, psych)
        twice = merge_pharmacology.add_pharmacology(once, psych)
        assert list(twice.columns) == list(once.columns)
        pd.testing.assert_frame_equal(twice, once)


class TestGuards:
    def test_an_rxcui_dtype_mismatch_raises_instead_of_blanking(self, merge_pharmacology):
        """Reading either file without dtype={"rxcui": str} must not pass silently."""
        master = master_frame([["704", "amitriptyline", "may_treat"]])
        psych = psych_frame([[704, AMITRIPTYLINE[1], AMITRIPTYLINE[2]]])
        with pytest.raises(ValueError, match="No rxcui"):
            merge_pharmacology.add_pharmacology(master, psych)

    def test_a_source_missing_its_pharmacology_columns_raises(self, merge_pharmacology):
        master = master_frame([["704", "amitriptyline", "may_treat"]])
        psych = pd.DataFrame([["704"]], columns=["rxcui"])
        with pytest.raises(ValueError, match="missing columns"):
            merge_pharmacology.add_pharmacology(master, psych)
