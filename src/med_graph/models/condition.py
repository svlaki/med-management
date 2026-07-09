from pydantic import BaseModel, ConfigDict, Field, field_validator

from med_graph.models.slug import validate_slug


class Condition(BaseModel):
    """A medical condition a medication may treat, e.g. major depressive disorder."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1, description="Stable slug, e.g. 'mdd'")
    name: str = Field(min_length=1)
    icd10: str | None = Field(default=None, description="ICD-10 code, e.g. 'F33'")

    @field_validator("id")
    @classmethod
    def normalize_id(cls, value: str) -> str:
        return validate_slug(value)
