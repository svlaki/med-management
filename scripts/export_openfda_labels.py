"""Query openFDA label endpoint for each drug in the clean drug universe.

For each unique drug in data_clean/drug_all_conditions.csv, fetches the FDA
label to determine regulatory status and approved indications.

Run: .venv/bin/python scripts/export_openfda_labels.py
Output: data_clean/openfda_labels.csv
"""

import os
import time
from pathlib import Path

import httpx
import pandas as pd
from dotenv import load_dotenv

from med_graph.sources.indication_match import approved_disorders
from med_graph.sources.lucene import escape_phrase

LABEL_URL = "https://api.fda.gov/drug/label.json"
DATA_DIR = Path(__file__).resolve().parent.parent / "data_clean"
DELAY = 0.25  # seconds between calls (anonymous limit is 240/min)


def fetch_label(http: httpx.Client, generic_name: str, api_key: str | None) -> dict | None:
    """Fetch the first openFDA label result for a drug, or None if not found."""
    params = {
        "search": f'openfda.generic_name:"{escape_phrase(generic_name)}"',
        "limit": "1",
    }
    if api_key:
        params["api_key"] = api_key
    try:
        response = http.get(LABEL_URL, params=params, timeout=30)
        if response.status_code != 200:
            return None
        results = response.json().get("results", [])
        return results[0] if results else None
    except httpx.HTTPError as error:
        print(f"    ! {generic_name} failed: {error}")
        return None


def main() -> None:
    load_dotenv()
    api_key = os.environ.get("OPENFDA_API_KEY")

    drugs_df = pd.read_csv(DATA_DIR / "drug_all_conditions.csv", dtype={"rxcui": str})
    unique_drugs = (
        drugs_df[["rxcui", "generic_name"]]
        .drop_duplicates(subset="rxcui")
        .sort_values("generic_name")
    )
    print(f"Querying openFDA labels for {len(unique_drugs)} drugs...\n")

    rows = []
    with httpx.Client() as http:
        for i, (_, drug) in enumerate(unique_drugs.iterrows()):
            if i:
                time.sleep(DELAY)
            label = fetch_label(http, drug["generic_name"], api_key)

            if label is None:
                rows.append({
                    "rxcui": drug["rxcui"],
                    "generic_name": drug["generic_name"],
                    "has_label": False,
                    "product_type": "",
                    "indications_and_usage": "",
                    "matched_disorders": "",
                })
            else:
                openfda = label.get("openfda", {})
                product_types = openfda.get("product_type", [])
                indications_text = " ".join(label.get("indications_and_usage", []))
                matched = approved_disorders(indications_text)

                rows.append({
                    "rxcui": drug["rxcui"],
                    "generic_name": drug["generic_name"],
                    "has_label": True,
                    "product_type": product_types[0] if product_types else "",
                    "indications_and_usage": indications_text,
                    "matched_disorders": "; ".join(matched),
                })

            if (i + 1) % 50 == 0:
                print(f"  {i + 1}/{len(unique_drugs)} drugs queried...")

    df = pd.DataFrame(rows)
    out_path = DATA_DIR / "openfda_labels.csv"
    df.to_csv(out_path, index=False)

    has_label = df[df.has_label]
    has_match = df[df.matched_disorders != ""]
    print(f"\nWrote {out_path}")
    print(f"  Total drugs: {len(df)}")
    print(f"  With label: {len(has_label)}")
    print(f"  Without label: {len(df) - len(has_label)}")
    print(f"  Product types: {has_label.product_type.value_counts().to_dict()}")
    print(f"  With matched psychiatric disorders: {len(has_match)}")


if __name__ == "__main__":
    main()
