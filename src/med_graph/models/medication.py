from pydantic import BaseModel, ConfigDict, Field


class Medication(BaseModel):
    """A medication, keyed by RxNorm concept ID so brand/generic resolve to one node."""

    model_config = ConfigDict(frozen=True)

    rxcui: str = Field(pattern=r"^\d+$", description="RxNorm concept unique identifier")
    name: str = Field(min_length=1)
    generic_name: str = Field(min_length=1)
    drug_class: str | None = Field(default=None, description="e.g. 'SSRI'")
