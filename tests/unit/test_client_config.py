import pytest

from med_graph.graph.client import GraphClient, GraphConfigError, GraphSchemaError


@pytest.fixture
def clean_env(monkeypatch):
    for name in ("NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD"):
        monkeypatch.delenv(name, raising=False)


def test_from_env_fails_without_config(clean_env):
    with pytest.raises(GraphConfigError, match="NEO4J_URI"):
        with GraphClient.from_env():
            pass


def test_from_env_names_the_missing_variable(clean_env, monkeypatch):
    monkeypatch.setenv("NEO4J_URI", "bolt://localhost:7687")
    monkeypatch.setenv("NEO4J_USER", "neo4j")
    with pytest.raises(GraphConfigError, match="NEO4J_PASSWORD"):
        with GraphClient.from_env():
            pass


class FailingDriver:
    """Fake driver whose queries always fail, for exercising error wrapping."""

    def execute_query(self, query, parameters_=None):
        raise RuntimeError("boom")


def test_apply_schema_reports_failing_statement():
    client = GraphClient(FailingDriver())
    with pytest.raises(GraphSchemaError, match="CREATE CONSTRAINT condition_id"):
        client.apply_schema()
