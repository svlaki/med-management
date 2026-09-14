"""Merge the psychiatric pharmacology columns into drug_master.csv.

Copies `neurotransmitters` and `mechanism` from data_exports/psych_drug_dataset.csv
onto data_clean/drug_master.csv, joined on rxcui. No network calls -- a pure local
reshape of two files that already exist.

drug_master.csv is long-format (one row per drug/rela pair), so a drug's
pharmacology repeats across its rows, the same way has_label and
indications_and_usage already do. Drugs outside the psychiatric dataset get "".

Run: .venv/bin/python scripts/merge_pharmacology.py
Output: updates data_clean/drug_master.csv in place
"""

from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "data_exports" / "psych_drug_dataset.csv"
DEST = REPO / "data_clean" / "drug_master.csv"

# Appended to drug_master in this order.
COLUMNS = ("neurotransmitters", "mechanism")


def read_csv(path: Path) -> pd.DataFrame:
    """Read a pipeline CSV, keeping rxcui as a string so joins line up."""
    try:
        return pd.read_csv(path, dtype={"rxcui": str})
    except FileNotFoundError as error:
        raise SystemExit(
            f"{path} not found. drug_master.csv is rebuilt by the export_* scripts; "
            f"psych_drug_dataset.csv by scripts/build_drug_dataset.py."
        ) from error
    except (pd.errors.ParserError, pd.errors.EmptyDataError) as error:
        raise SystemExit(f"Could not parse {path}: {error}") from error


def add_pharmacology(master: pd.DataFrame, psych: pd.DataFrame) -> pd.DataFrame:
    """Return a new frame with the psych pharmacology columns joined on rxcui.

    Raises ValueError if no rxcui matches -- almost always a dtype slip, which
    would otherwise blank both columns silently.
    """
    missing = [c for c in ("rxcui", *COLUMNS) if c not in psych.columns]
    if missing:
        raise ValueError(f"{SRC.name} is missing columns: {', '.join(missing)}")

    matched = master.rxcui.isin(set(psych.rxcui)).sum()
    if not matched:
        raise ValueError(
            "No rxcui in drug_master.csv matched psych_drug_dataset.csv; "
            "check both files were read with dtype={'rxcui': str}."
        )

    return master.assign(**{
        column: master.rxcui.map(dict(zip(psych.rxcui, psych[column].fillna(""))))
        .fillna("")
        for column in COLUMNS
    })


def main() -> None:
    master = read_csv(DEST)
    psych = read_csv(SRC)

    merged = add_pharmacology(master, psych)
    merged.to_csv(DEST, index=False)

    drugs = merged.drop_duplicates(subset="rxcui")
    print(f"Updated {DEST.relative_to(REPO)}")
    print(f"  {len(merged)} rows, {len(drugs)} drugs, {len(merged.columns)} columns")
    for column in COLUMNS:
        filled = (drugs[column] != "").sum()
        print(f"  Drugs with {column}: {filled}/{len(drugs)}")


if __name__ == "__main__":
    main()
