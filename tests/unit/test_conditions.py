from med_graph.sources.conditions import CONDITION_REGISTRY


def test_mdd_is_registered():
    spec = CONDITION_REGISTRY["mdd"]
    assert spec.condition.id == "mdd"
    assert spec.condition.icd10 == "F33"


def test_mdd_queries_both_specific_and_parent_rxclass_ids():
    spec = CONDITION_REGISTRY["mdd"]
    assert spec.rxclass_ids == ("D003865", "D003866")


def test_registry_keys_match_condition_ids():
    for key, spec in CONDITION_REGISTRY.items():
        assert key == spec.condition.id
