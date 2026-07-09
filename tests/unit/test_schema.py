from med_graph.graph.schema import SCHEMA_STATEMENTS


def test_has_unique_constraints_for_all_node_keys():
    joined = " ".join(SCHEMA_STATEMENTS)
    assert "(c:Condition) REQUIRE c.id IS UNIQUE" in joined
    assert "(m:Medication) REQUIRE m.rxcui IS UNIQUE" in joined
    assert "(s:SideEffect) REQUIRE s.id IS UNIQUE" in joined


def test_all_statements_are_idempotent():
    for statement in SCHEMA_STATEMENTS:
        assert "IF NOT EXISTS" in statement
