"""Contract every data source adapter implements.

Adapters (RxClass, openFDA, FAERS, ...) fetch raw data and emit validated
models plus provenance-tagged edges. The ingest pipeline only depends on
this protocol, so adding a source never touches the graph layer.
"""

from typing import Protocol

from pydantic import BaseModel, ConfigDict

from med_graph.models import CausesEdge, Medication, SideEffect, TreatsEdge
from med_graph.sources.conditions import ConditionSpec


class SourceFetchError(Exception):
    """Raised when a data source cannot be fetched or parsed."""


class SourceBatch(BaseModel):
    """Everything one source knows about one condition, ready to load."""

    model_config = ConfigDict(frozen=True)

    medications: tuple[Medication, ...] = ()
    side_effects: tuple[SideEffect, ...] = ()
    treats: tuple[TreatsEdge, ...] = ()
    causes: tuple[CausesEdge, ...] = ()


class DataSource(Protocol):
    def fetch(self, spec: ConditionSpec) -> SourceBatch:
        """Fetch all medications and side effects this source knows for a condition."""
        ...


class EnrichmentSource(Protocol):
    def enrich(self, medications: tuple[Medication, ...]) -> SourceBatch:
        """Fetch additional facts (e.g. side effects) for already-known medications."""
        ...
