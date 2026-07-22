"""Dump the RAW RxClass pharmacology classes per drug (before any parsing).

For every drug in the universe, fetch RxClass `class/byRxcui` and write one row
per (drug, class): the unparsed ATC / MoA / PE / DISEASE classes exactly as
RxClass returns them, so the derived drug_class / mechanism / neurotransmitters /
may_treat columns can be audited against their source. RxClass has no rate limit.

Run: .venv/bin/python scripts/export_pharmacology_raw.py
Output: data_exports/raw/raw_rxclass_pharmacology.csv
"""

import time
from pathlib import Path

import httpx
import pandas as pd

BYRXCUI_URL = "https://rxnav.nlm.nih.gov/REST/rxclass/class/byRxcui.json"
RAW_DIR = Path(__file__).resolve().parent.parent / "data_exports" / "raw"


def main() -> None:
    labels = pd.read_csv(RAW_DIR / "raw_openfda_labels.csv", dtype={"rxcui": str})
    labels = labels[labels.rxcui.notna()]

    rows = []
    with httpx.Client() as http:
        for i, (rxcui, name) in enumerate(zip(labels.rxcui, labels.generic_name)):
            try:
                resp = http.get(BYRXCUI_URL, params={"rxcui": rxcui}, timeout=30)
                resp.raise_for_status()
                info = (
                    resp.json()
                    .get("rxclassDrugInfoList", {})
                    .get("rxclassDrugInfo", [])
                )
            except httpx.HTTPError as error:
                print(f"    ! {name} ({rxcui}) failed: {error}")
                info = []
            for item in info:
                concept = item.get("rxclassMinConceptItem", {})
                rows.append({
                    "rxcui": rxcui,
                    "generic_name": name,
                    "class_type": concept.get("classType"),
                    "class_id": concept.get("classId"),
                    "class_name": concept.get("className"),
                    "rela": item.get("rela"),
                    "rela_source": item.get("relaSource"),
                })
            if i % 25 == 0:
                print(f"  {i + 1}/{len(labels)}  {name}")
            time.sleep(0.03)

    df = pd.DataFrame(rows)
    out = RAW_DIR / "raw_rxclass_pharmacology.csv"
    df.to_csv(out, index=False)
    print(f"\nWrote {out}  ({len(df)} rows across {df.rxcui.nunique()} drugs)")
    print("class_type counts:", df.class_type.value_counts().to_dict())


if __name__ == "__main__":
    main()
