from med_graph.sources.dataset_conditions import canonical_condition


def test_preserves_existing_slugs():
    assert canonical_condition("Major Depressive Disorder").id == "mdd"
    assert canonical_condition("Bipolar Disorder").id == "bipolar"
    assert canonical_condition("Generalized Anxiety Disorder").id == "gad"


def test_merges_abbreviation_and_full_name():
    # Both the abbreviation and the MeSH label collapse to one node.
    assert canonical_condition("ADHD").id == "adhd"
    assert canonical_condition("Attention Deficit Disorder with Hyperactivity").id == "adhd"
    assert canonical_condition("OCD").id == canonical_condition(
        "Obsessive-Compulsive Disorder"
    ).id


def test_merges_ptsd_variants():
    assert canonical_condition("PTSD").id == "ptsd"
    assert canonical_condition("Stress Disorders, Post-Traumatic").id == "ptsd"


def test_carries_display_name_and_icd10():
    ptsd = canonical_condition("PTSD")
    assert ptsd.name == "Post-Traumatic Stress Disorder"
    assert ptsd.icd10 == "F43.1"


def test_is_case_insensitive():
    assert canonical_condition("bipolar disorder").id == "bipolar"


def test_unknown_name_falls_back_to_slug():
    condition = canonical_condition("Some Rare Disorder")
    assert condition.id == "some-rare-disorder"
    assert condition.name == "Some Rare Disorder"
    assert condition.icd10 is None
