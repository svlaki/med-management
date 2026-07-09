'''
Pydantic model for a SideEffect node. Fields: id (auto-slugified), name, optional meddra_term. Frozen.
'''

from pydantic import BaseModel, ConfigDict, Field, field_validator
from med_graph.models.slug import validate_slug


class SideEffect(BaseModel):
    """An adverse effect, canonicalized so term variants collapse to one node."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1, description="Canonical slug, e.g. 'weight-gain'")
    name: str = Field(min_length=1)
    meddra_term: str | None = Field(default=None, description="MedDRA preferred term")

    @field_validator("id")
    @classmethod
    def normalize_id(cls, value: str) -> str:
        return validate_slug(value)
