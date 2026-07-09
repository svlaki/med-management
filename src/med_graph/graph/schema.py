"""Graph constraints and indexes. All statements are idempotent so re-runs are safe."""

SCHEMA_STATEMENTS: tuple[str, ...] = (
    "CREATE CONSTRAINT condition_id IF NOT EXISTS "
    "FOR (c:Condition) REQUIRE c.id IS UNIQUE",
    "CREATE CONSTRAINT medication_rxcui IF NOT EXISTS "
    "FOR (m:Medication) REQUIRE m.rxcui IS UNIQUE",
    "CREATE CONSTRAINT side_effect_id IF NOT EXISTS "
    "FOR (s:SideEffect) REQUIRE s.id IS UNIQUE",
    "CREATE INDEX medication_generic_name IF NOT EXISTS "
    "FOR (m:Medication) ON (m.generic_name)",
    "CREATE INDEX side_effect_name IF NOT EXISTS "
    "FOR (s:SideEffect) ON (s.name)",
)
