"""Aggregate the comprehensive psychiatric-drug dataset CSV.

Combines local raw exports (data_exports/raw/) with a fresh RxClass pharmacology
pull into one row per drug. No graph, no database — pure aggregation.

Columns: rxcui, generic_name, drug_class, atc_codes, neurotransmitters, mechanism,
fda_approved, approved_for, may_treat, label_confirmed_side_effects,
faers_only_side_effects.

Run (after scripts/export_raw_api.py): .venv/bin/python scripts/build_drug_dataset.py
"""

import time
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
from dotenv import load_dotenv

from med_graph.sources.base import SourceFetchError
from med_graph.sources.indication_match import approved_disorders
from med_graph.sources.openfda import ADMINISTRATIVE_TERMS
from med_graph.sources.openfda_label import label_mentions
from med_graph.sources.rxclass_pharmacology import RxClassPharmacologySource


def normalize_spelling(text: str) -> str:
    """Fold British medical spelling to American so FAERS terms (DIARRHOEA) match
    US label text (diarrhea). Safe here — we only look up clinical terms."""
    return text.lower().replace("oe", "e").replace("ae", "e")

EMPTY_PHARMACOLOGY = {
    "atc_codes": [], "drug_class": "Other", "mechanisms": [],
    "neurotransmitters": [], "may_treat": [],
}


def fetch_pharmacology(pharm: RxClassPharmacologySource, rxcui: str, attempts: int = 3) -> dict:
    """Fetch one drug's pharmacology, tolerating transient network failures so a
    single flaky RxClass call doesn't abort the whole dataset."""
    for attempt in range(attempts):
        try:
            return pharm.pharmacology(rxcui)
        except SourceFetchError:
            if attempt == attempts - 1:
                return dict(EMPTY_PHARMACOLOGY)
            time.sleep(1.5)
    return dict(EMPTY_PHARMACOLOGY)

DATA_DIR = Path(__file__).resolve().parent.parent / "data_exports"
RAW_DIR = DATA_DIR / "raw"
OUT_CSV = DATA_DIR / "psych_drug_dataset.csv"
TOP_N = 15  # side effects listed per drug, per bucket


def psychiatric_disorder_names() -> set[str]:
    df = pd.read_csv(DATA_DIR / "psychiatric_disorders.csv")
    return {name.lower() for name in df.loc[df.drug_status == "populated", "class_name"]}


def faers_by_rxcui() -> dict[str, list[tuple[str, int]]]:
    df = pd.read_csv(RAW_DIR / "raw_faers_reactions.csv", dtype={"rxcui": str})
    df = df.sort_values("report_count", ascending=False)
    out: dict[str, list[tuple[str, int]]] = {}
    for rxcui, group in df.groupby("rxcui"):
        out[rxcui] = list(zip(group.reaction_term, group.report_count))
    return out


def split_side_effects(reactions, adverse_text):
    """Split a drug's FAERS reactions into (label-confirmed, faers-only) by whether
    the term appears in the label's adverse-reactions text. Administrative FAERS
    terms (drug ineffective, off-label use, ...) are dropped from both buckets;
    matching folds British spelling so DIARRHOEA confirms against 'diarrhea'."""
    normalized_label = normalize_spelling(adverse_text)
    confirmed, faers_only = [], []
    for term, _count in reactions:
        if not isinstance(term, str) or term.upper() in ADMINISTRATIVE_TERMS:
            continue
        folded = normalize_spelling(term)
        effect = SimpleNamespace(meddra_term=folded, name=folded)
        (confirmed if label_mentions(effect, normalized_label) else faers_only).append(
            term.capitalize()
        )
    return confirmed[:TOP_N], faers_only[:TOP_N]


def main() -> None:
    load_dotenv()
    labels = pd.read_csv(RAW_DIR / "raw_openfda_labels.csv", dtype={"rxcui": str})
    labels = labels[labels.rxcui.notna()]
    psych_names = psychiatric_disorder_names()
    faers = faers_by_rxcui()

    rows = []
    missing_pharm = []
    with RxClassPharmacologySource() as pharm:
        for i, drug in labels.iterrows():
            rxcui = str(drug.rxcui)
            pharma = fetch_pharmacology(pharm, rxcui)

            indications = drug.indications_and_usage if isinstance(drug.indications_and_usage, str) else ""
            adverse = drug.adverse_reactions if isinstance(drug.adverse_reactions, str) else ""
            approved = approved_disorders(indications)
            may_treat = [d for d in pharma["may_treat"] if d.lower() in psych_names]
            confirmed, faers_only = split_side_effects(faers.get(rxcui, []), adverse)

            if pharma["drug_class"] == "Other" and not pharma["neurotransmitters"]:
                missing_pharm.append(drug.generic_name)

            rows.append({
                "rxcui": rxcui,
                "generic_name": drug.generic_name,
                "drug_class": pharma["drug_class"],
                "atc_codes": "; ".join(pharma["atc_codes"]),
                "neurotransmitters": "; ".join(f"{nt}({d})" for nt, d in pharma["neurotransmitters"]),
                "mechanism": "; ".join(pharma["mechanisms"]),
                "fda_approved": bool(approved),
                "approved_for": "; ".join(approved),
                "may_treat": "; ".join(may_treat),
                "label_confirmed_side_effects": "; ".join(confirmed),
                "faers_only_side_effects": "; ".join(faers_only),
            })
            if (i + 1) % 25 == 0:
                print(f"  {i + 1}/{len(labels)} drugs")

    df = pd.DataFrame(rows).sort_values(["drug_class", "generic_name"])
    df.to_csv(OUT_CSV, index=False)
    with pd.ExcelWriter(DATA_DIR / "psych_drug_dataset.xlsx") as writer:
        df.to_excel(writer, sheet_name="psych_drugs", index=False)

    print(f"\nWrote {OUT_CSV}  ({len(df)} drugs)")
    print("by drug_class:", df.drug_class.value_counts().to_dict())
    print(f"FDA-approved for >=1 tracked disorder: {int(df.fda_approved.sum())}")
    if missing_pharm:
        print(f"No ATC class or neurotransmitter (curate): {len(missing_pharm)} — "
              f"{', '.join(missing_pharm[:10])}")


if __name__ == "__main__":
    main()
