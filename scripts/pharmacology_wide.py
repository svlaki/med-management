"""Pivot the long raw pharmacology dump into a wide, one-row-per-drug view.

Reads data_exports/raw/raw_rxclass_pharmacology.csv (one row per drug-class
pairing) and collapses each drug's positive class memberships into readable
columns. Keeps contraindications in a separate column so the has_* vs ci_*
distinction stays visible. No API calls — pure reshape of the existing file.

Run: .venv/bin/python scripts/pharmacology_wide.py
Output: data_exports/raw/raw_rxclass_pharmacology_wide.csv (+ .xlsx sheet)
"""

from pathlib import Path

import pandas as pd

RAW_DIR = Path(__file__).resolve().parent.parent / "data_exports" / "raw"
SRC = RAW_DIR / "raw_rxclass_pharmacology.csv"

# Output column -> (class_type, set of accepted `rela` values). None = any rela.
COLUMNS: dict[str, tuple[str, set[str] | None]] = {
    "atc_classes": ("ATC1-4", None),
    "established_pharm_class": ("EPC", {"has_epc"}),
    "mechanism_of_action": ("MOA", {"has_moa"}),
    "physiologic_effects": ("PE", {"has_pe"}),
    "may_treat": ("DISEASE", {"may_treat"}),
    "contraindicated_with": ("DISEASE", {"ci_with"}),
    "va_class": ("VA", {"has_VAClass", "has_VAClass_extended"}),
    "dea_schedule": ("SCHEDULE", None),
}


def _collapse(group: pd.DataFrame, class_type: str, relas: set[str] | None) -> str:
    sub = group[group.class_type == class_type]
    if relas is not None:
        sub = sub[sub.rela.isin(relas)]
    names = sorted({n for n in sub.class_name.dropna()})
    return "; ".join(names)


def main() -> None:
    df = pd.read_csv(SRC)
    rows = []
    for rxcui, group in df.groupby("rxcui"):
        row = {"rxcui": rxcui, "generic_name": group.generic_name.iloc[0]}
        for col, (class_type, relas) in COLUMNS.items():
            row[col] = _collapse(group, class_type, relas)
        rows.append(row)

    wide = pd.DataFrame(rows).sort_values("generic_name")
    out_csv = RAW_DIR / "raw_rxclass_pharmacology_wide.csv"
    wide.to_csv(out_csv, index=False)
    with pd.ExcelWriter(RAW_DIR / "raw_rxclass_pharmacology_wide.xlsx") as writer:
        wide.to_excel(writer, sheet_name="pharmacology_wide", index=False)

    print(f"Wrote {out_csv}  ({len(wide)} drugs, one row each)")
    print("Columns:", list(wide.columns))


if __name__ == "__main__":
    main()
