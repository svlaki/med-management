"""Registry of conditions the system knows how to ingest.

Adding a condition (PTSD, schizoaffective disorder, ...) means adding an
entry here — source adapters and the graph layer are condition-agnostic.
"""

from pydantic import BaseModel, ConfigDict

from med_graph.models import Condition


class ConditionSpec(BaseModel):
    """A condition plus the external vocabulary IDs needed to query sources for it."""

    model_config = ConfigDict(frozen=True)

    condition: Condition
    rxclass_ids: tuple[str, ...]


CONDITION_REGISTRY: dict[str, ConditionSpec] = {
    "mdd": ConditionSpec(
        condition=Condition(id="mdd", name="Major Depressive Disorder", icd10="F33"),
        # D003865 = Major Depressive Disorder (specific), D003866 = Depressive
        # Disorder (parent class, where most antidepressants are indexed)
        rxclass_ids=("D003865", "D003866"),
    ),
}
