from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from med_graph.models.slug import validate_slug


class EdgeSource(StrEnum):
    """Provenance of a relationship — every edge must say where it came from."""

    RXCLASS = "rxclass"
    OPENFDA_LABEL = "openfda_label"
    FAERS = "faers"


class Frequency(StrEnum):
    """CIOMS frequency bands used on drug labels."""

    VERY_COMMON = "very_common"  # >= 1/10
    COMMON = "common"  # 1/100 to 1/10
    UNCOMMON = "uncommon"  # 1/1000 to 1/100
    RARE = "rare"  # < 1/1000
    UNKNOWN = "unknown"


class TreatsEdge(BaseModel):
    """(:Medication)-[:TREATS]->(:Condition)"""

    model_config = ConfigDict(frozen=True)

    medication_rxcui: str = Field(pattern=r"^\d+$")
    condition_id: str = Field(min_length=1)
    source: EdgeSource
    approval_status: str = Field(default="approved")

    @field_validator("condition_id")
    @classmethod
    def normalize_condition_id(cls, value: str) -> str:
        return validate_slug(value)


class CausesEdge(BaseModel):
    """(:Medication)-[:CAUSES]->(:SideEffect)"""

    model_config = ConfigDict(frozen=True)

    medication_rxcui: str = Field(pattern=r"^\d+$")
    side_effect_id: str = Field(min_length=1)
    source: EdgeSource
    frequency: Frequency = Frequency.UNKNOWN
    severity: str | None = None
    report_count: int | None = Field(
        default=None, gt=0, description="FAERS adverse-event report count"
    )

    @field_validator("side_effect_id")
    @classmethod
    def normalize_side_effect_id(cls, value: str) -> str:
        return validate_slug(value)
