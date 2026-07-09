"""Typed, immutable result rows returned by the query layer."""

from pydantic import BaseModel, ConfigDict


class SideEffectReport(BaseModel):
    """One side effect reported for a medication, with its FAERS report volume."""

    model_config = ConfigDict(frozen=True)

    side_effect_id: str
    name: str
    source: str
    report_count: int | None
    label_confirmed: bool | None = None


class MedicationSummary(BaseModel):
    """A medication that treats a condition, with how many side effects it has."""

    model_config = ConfigDict(frozen=True)

    rxcui: str
    generic_name: str
    drug_class: str | None
    side_effect_count: int


class MedicationCause(BaseModel):
    """A medication reported to cause a given side effect, with its report volume."""

    model_config = ConfigDict(frozen=True)

    rxcui: str
    generic_name: str
    report_count: int | None
