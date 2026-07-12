from med_graph.sources.conditions import CONDITION_REGISTRY


def test_mdd_is_registered():
    spec = CONDITION_REGISTRY["mdd"]
    assert spec.condition.id == "mdd"
    assert spec.condition.icd10 == "F33"


def test_mdd_queries_both_specific_and_parent_rxclass_ids():
    spec = CONDITION_REGISTRY["mdd"]
    assert spec.rxclass_ids == ("D003865", "D003866")


def test_bipolar_is_registered():
    spec = CONDITION_REGISTRY["bipolar"]
    assert spec.condition.id == "bipolar"
    assert spec.condition.name == "Bipolar Disorder"
    assert spec.condition.icd10 == "F31"


def test_bipolar_queries_both_specific_and_parent_rxclass_ids():
    spec = CONDITION_REGISTRY["bipolar"]
    assert spec.rxclass_ids == ("D001714", "D000068105")


def test_gad_is_registered():
    spec = CONDITION_REGISTRY["gad"]
    assert spec.condition.id == "gad"
    assert spec.condition.name == "Generalized Anxiety Disorder"
    assert spec.condition.icd10 == "F41.1"


def test_gad_queries_specific_and_parent_rxclass_ids():
    spec = CONDITION_REGISTRY["gad"]
    assert spec.rxclass_ids == ("D000098647", "D001008")


def test_registry_keys_match_condition_ids():
    for key, spec in CONDITION_REGISTRY.items():
        assert key == spec.condition.id
