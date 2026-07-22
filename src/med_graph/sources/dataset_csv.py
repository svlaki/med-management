"""Parse psych_drug_dataset.csv into per-condition graph batches.

Pure file parsing, no network. Each drug row becomes a Medication (with its
pharmacology columns), TREATS edges to the conditions it's approved for or may
treat, and CAUSES edges to its side effects. FAERS report counts — dropped from
the summary CSV — are rejoined from data_exports/raw/raw_faers_reactions.csv so
the graph keeps its report volumes.
"""

import csv
from pathlib import Path

from med_graph.models import (
    CausesEdge,
    Condition,
    EdgeSource,
    Medication,
    SideEffect,
    TreatsEdge,
)
from med_graph.models.slug import slugify
from med_graph.sources.base import SourceBatch
from med_graph.sources.dataset_conditions import canonical_condition


def _split(cell: str | None) -> list[str]:
    """Split a semicolon-delimited dataset cell into trimmed, non-empty terms."""
    if not cell:
        return []
    return [term.strip() for term in cell.split(";") if term.strip()]


def _faers_counts(faers_path: Path) -> dict[tuple[str, str], int]:
    """Map (rxcui, UPPERCASED reaction term) -> report_count from raw FAERS.

    The summary CSV keeps FAERS' original spelling (e.g. British 'Diarrhoea'),
    so an uppercased exact match reunites each term with its count.
    """
    counts: dict[tuple[str, str], int] = {}
    with faers_path.open(newline="") as handle:
        for row in csv.DictReader(handle):
            try:
                count = int(row["report_count"])
            except (KeyError, ValueError):
                continue
            counts[(row["rxcui"], row["reaction_term"].upper())] = count
    return counts


def _medication(row: dict[str, str]) -> Medication:
    def clean(value: str | None) -> str | None:
        text = (value or "").strip()
        return text or None

    return Medication(
        rxcui=row["rxcui"].strip(),
        name=row["generic_name"].strip(),
        generic_name=row["generic_name"].strip(),
        drug_class=clean(row.get("drug_class")),
        atc_codes=clean(row.get("atc_codes")),
        mechanism=clean(row.get("mechanism")),
        neurotransmitters=clean(row.get("neurotransmitters")),
    )


def _treats_edges(row: dict[str, str]) -> list[tuple[Condition, TreatsEdge]]:
    """Build a med's (Condition, TREATS edge) pairs. approved_for wins over
    may_treat when a condition appears in both, and duplicate slugs (synonyms)
    collapse to one."""
    rxcui = row["rxcui"].strip()
    by_slug: dict[str, tuple[Condition, TreatsEdge]] = {}
    for cell, approved in ((row.get("approved_for"), True), (row.get("may_treat"), False)):
        for raw_name in _split(cell):
            condition = canonical_condition(raw_name)
            existing = by_slug.get(condition.id)
            # Keep the stronger (approved) edge if we've already seen this slug.
            if existing is not None and existing[1].fda_approved:
                continue
            by_slug[condition.id] = (
                condition,
                TreatsEdge(
                    medication_rxcui=rxcui,
                    condition_id=condition.id,
                    source=EdgeSource.RXCLASS,
                    fda_approved=approved,
                ),
            )
    return list(by_slug.values())


def _side_effects(
    row: dict[str, str], counts: dict[tuple[str, str], int]
) -> tuple[list[SideEffect], list[CausesEdge]]:
    rxcui = row["rxcui"].strip()
    effects: dict[str, SideEffect] = {}
    edges: dict[str, CausesEdge] = {}
    for column, confirmed in (
        ("label_confirmed_side_effects", True),
        ("faers_only_side_effects", False),
    ):
        for term in _split(row.get(column)):
            slug = slugify(term)
            if not slug or slug in edges:
                continue
            effects[slug] = SideEffect(id=slug, name=term)
            edges[slug] = CausesEdge(
                medication_rxcui=rxcui,
                side_effect_id=slug,
                source=EdgeSource.FAERS,
                report_count=counts.get((rxcui, term.upper())),
                label_confirmed=confirmed,
            )
    return list(effects.values()), list(edges.values())


def build_dataset_batches(
    csv_path: Path, faers_path: Path
) -> list[tuple[Condition, SourceBatch]]:
    """Parse the dataset into one (Condition, SourceBatch) pair per condition,
    each ready to feed :func:`med_graph.graph.loader.load_batch`.

    A medication treating several conditions appears in each of their batches;
    MERGE-based loading dedupes it, so this is safe and keeps every condition's
    batch self-contained.
    """
    counts = _faers_counts(faers_path)

    conditions: dict[str, Condition] = {}
    meds_by_condition: dict[str, list[Medication]] = {}
    effects_by_condition: dict[str, dict[str, SideEffect]] = {}
    treats_by_condition: dict[str, list[TreatsEdge]] = {}
    causes_by_condition: dict[str, list[CausesEdge]] = {}

    with csv_path.open(newline="") as handle:
        for row in csv.DictReader(handle):
            medication = _medication(row)
            treats = _treats_edges(row)
            if not treats:
                continue  # a drug with no condition links has nothing to graph
            med_effects, med_causes = _side_effects(row, counts)

            for condition, edge in treats:
                slug = condition.id
                conditions.setdefault(slug, condition)
                meds_by_condition.setdefault(slug, []).append(medication)
                treats_by_condition.setdefault(slug, []).append(edge)
                bucket = effects_by_condition.setdefault(slug, {})
                for effect in med_effects:
                    bucket[effect.id] = effect
                causes_by_condition.setdefault(slug, []).extend(med_causes)

    return [
        (
            condition,
            SourceBatch(
                medications=tuple(meds_by_condition[slug]),
                side_effects=tuple(effects_by_condition.get(slug, {}).values()),
                treats=tuple(treats_by_condition[slug]),
                causes=tuple(causes_by_condition.get(slug, [])),
            ),
        )
        for slug, condition in conditions.items()
    ]
