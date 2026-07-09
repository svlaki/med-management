"""
A Protocol defining a single execute(query, params) method. This abstraction lets loader and query layers be tested with fakes
instead of requiring a real Neo4j connection.

The minimal read/write interface the loader and query layer depend on. Depending on this Protocol rather than the concrete GraphClient 
keeps those modules testable with lightweight fakes and free of a Neo4j import.
"""

from typing import Any, Protocol

class GraphExecutor(Protocol):
    def execute(
        self, query: str, parameters: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]: ...
