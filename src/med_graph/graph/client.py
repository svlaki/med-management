import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from neo4j import Driver, GraphDatabase

from med_graph.graph.schema import SCHEMA_STATEMENTS


class GraphConfigError(Exception):
    """Raised when required Neo4j connection settings are missing."""


class GraphSchemaError(Exception):
    """Raised when a schema statement fails to apply."""


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise GraphConfigError(f"{name} is not configured; see .env.example")
    return value


class GraphClient:
    """Thin wrapper around the Neo4j driver for this project's graph."""

    def __init__(self, driver: Driver) -> None:
        self._driver = driver

    @classmethod
    @contextmanager
    def from_env(cls) -> Iterator["GraphClient"]:
        uri = _require_env("NEO4J_URI")
        user = _require_env("NEO4J_USER")
        password = _require_env("NEO4J_PASSWORD")
        with GraphDatabase.driver(uri, auth=(user, password)) as driver:
            driver.verify_connectivity()
            yield cls(driver)

    def execute(self, query: str, parameters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Run a Cypher query.

        Query text must be a static string — never interpolate runtime values
        into it. All runtime values go through `parameters`.
        """
        records, _, _ = self._driver.execute_query(query, parameters_=parameters or {})
        return [record.data() for record in records]

    def apply_schema(self) -> None:
        for statement in SCHEMA_STATEMENTS:
            try:
                self.execute(statement)
            except Exception as error:
                raise GraphSchemaError(
                    f"Failed applying schema statement: {statement}"
                ) from error
