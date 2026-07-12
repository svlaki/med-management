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
    # Phrases searched against openFDA label `indications_and_usage` to mark
    # which medications are FDA-approved (on-label) for this condition.
    label_indication_terms: tuple[str, ...] = ()


CONDITION_REGISTRY: dict[str, ConditionSpec] = {
    "mdd": ConditionSpec(
        condition=Condition(id="mdd", name="Major Depressive Disorder", icd10="F33"),
        # D003865 = Major Depressive Disorder (specific), D003866 = Depressive
        # Disorder (parent class, where most antidepressants are indexed)
        rxclass_ids=("D003865", "D003866"),
        label_indication_terms=("major depressive disorder",),
    ),
    "bipolar": ConditionSpec(
        condition=Condition(id="bipolar", name="Bipolar Disorder", icd10="F31"),
        # RxClass has no bipolar II class (checked 2026-07): D001714 = Bipolar
        # Disorder (specific), D000068105 = Bipolar and Related Disorders
        # (parent). Their member sets are identical today; both included and
        # deduped for future-proofing.
        rxclass_ids=("D001714", "D000068105"),
        label_indication_terms=("bipolar disorder", "bipolar depression", "manic"),
    ),
    "gad": ConditionSpec(
        condition=Condition(
            id="gad", name="Generalized Anxiety Disorder", icd10="F41.1"
        ),
        # The GAD-specific class D000098647 exists but has 0 members (checked
        # 2026-07), so members come from the broad parent D001008 "Anxiety
        # Disorders" (~52 drugs, wider than GAD alone). Specific class kept for
        # future-proofing; deduped with the parent.
        rxclass_ids=("D000098647", "D001008"),
        label_indication_terms=("generalized anxiety disorder",),
    ),
}
