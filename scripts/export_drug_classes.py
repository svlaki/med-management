"""Fetch ATC-derived drug class for each drug in the master dataset.

For each unique drug in drug_master.csv, calls the RxClass byRxcui endpoint to
get ATC codes, then maps them to one of 8 therapeutic classes.

Run: .venv/bin/python scripts/export_drug_classes.py
Output: data_clean/drug_classes.csv
"""

import time
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from med_graph.sources.base import SourceFetchError
from med_graph.sources.rxclass_pharmacology import RxClassPharmacologySource

DATA_DIR = Path(__file__).resolve().parent.parent / "data_clean"

# ATC prefix -> drug class. Most-specific prefix first so N05AN (lithium)
# is matched before N05A (antipsychotic).
ATC_CLASS_MAP: list[tuple[str, str]] = [
    ("N05AN", "Mood Stabilizer"),
    ("N05A", "Antipsychotic"),
    ("N05B", "Anxiolytic"),
    ("N05C", "Sedative"),
    ("N06A", "Antidepressant"),
    ("N06B", "Stimulant"),
    ("N06D", "Anti-dementia"),
    ("N03A", "Mood Stabilizer"),
]

CLASS_PRIORITY = [
    "Antipsychotic",
    "Antidepressant",
    "Mood Stabilizer",
    "Stimulant",
    "Anxiolytic",
    "Sedative",
    "Anti-dementia",
]

# Manual overrides for drugs the ATC mis-classifies. Map to one of our 8 classes.
DRUG_CLASS_OVERRIDES: dict[str, str] = {
    "gabapentin": "Mood Stabilizer",
    "clonidine": "Other",
    "guanfacine": "Other",
    "diphenhydramine": "Sedative",
    "doxylamine": "Sedative",
    "bromodiphenhydramine": "Sedative",
    "cyproheptadine": "Other",
    "propranolol": "Other",
    "pramipexole": "Other",
    "selegiline": "Antidepressant",
    "piperacetazine": "Antipsychotic",
    "tetrazepam": "Anxiolytic",
    "thiamylal": "Sedative",
    "thiobutabarbital": "Sedative",
}


def atc_to_class(atc_codes: list[str]) -> str:
    """Map ATC codes to one of 8 drug classes."""
    matched: set[str] = set()
    for code in atc_codes:
        for prefix, cls in ATC_CLASS_MAP:
            if code.startswith(prefix):
                matched.add(cls)
                break
    for cls in CLASS_PRIORITY:
        if cls in matched:
            return cls
    return "Other"


def fetch_pharmacology(pharm: RxClassPharmacologySource, rxcui: str) -> dict:
    """Fetch one drug's pharmacology, tolerating transient failures."""
    for attempt in range(3):
        try:
            return pharm.pharmacology(rxcui)
        except SourceFetchError:
            if attempt == 2:
                return {"atc_codes": [], "drug_class": "Other"}
            time.sleep(1.5)
    return {"atc_codes": [], "drug_class": "Other"}


def main() -> None:
    load_dotenv()
    master = pd.read_csv(DATA_DIR / "drug_master.csv", dtype={"rxcui": str})
    unique_drugs = (
        master[["rxcui", "generic_name"]]
        .drop_duplicates(subset="rxcui")
        .sort_values("generic_name")
    )
    print(f"Fetching drug classes for {len(unique_drugs)} drugs...\n")

    rows = []
    with RxClassPharmacologySource() as pharm:
        for i, (_, drug) in enumerate(unique_drugs.iterrows()):
            rxcui = drug["rxcui"]
            name = drug["generic_name"]

            if name in DRUG_CLASS_OVERRIDES:
                drug_class = DRUG_CLASS_OVERRIDES[name]
                atc_codes = ""
            else:
                pharma = fetch_pharmacology(pharm, rxcui)
                atc_codes = "; ".join(pharma.get("atc_codes", []))
                drug_class = atc_to_class(pharma.get("atc_codes", []))

            rows.append({
                "rxcui": rxcui,
                "generic_name": name,
                "drug_class": drug_class,
                "atc_codes": atc_codes,
            })

            if (i + 1) % 50 == 0:
                print(f"  {i + 1}/{len(unique_drugs)} drugs queried...")

    df = pd.DataFrame(rows)
    out_path = DATA_DIR / "drug_classes.csv"
    df.to_csv(out_path, index=False)

    print(f"\nWrote {out_path}")
    print(f"  Total drugs: {len(df)}")
    print(f"  Class distribution:")
    for cls, count in df.drug_class.value_counts().items():
        print(f"    {cls}: {count}")


if __name__ == "__main__":
    main()
