"""Query FAERS for side effects and merge into drug_master.csv.

For each unique drug in drug_master.csv, fetches all reported adverse event
reaction terms from the FAERS endpoint, then adds a faers_side_effects column.

Run: .venv/bin/python scripts/export_faers.py
Output: updates data_clean/drug_master.csv in place
        also writes data_clean/faers_raw.csv (per-drug, per-reaction rows)
"""

import os
import time
from pathlib import Path

import httpx
import pandas as pd
from dotenv import load_dotenv

from med_graph.sources.lucene import escape_phrase

FAERS_URL = "https://api.fda.gov/drug/event.json"
DATA_DIR = Path(__file__).resolve().parent.parent / "data_clean"
DELAY = 0.25  # seconds between calls (anonymous limit is 240/min)


def fetch_reactions(http: httpx.Client, generic_name: str, api_key: str | None) -> list[dict]:
    """Fetch all FAERS reaction terms and counts for a drug."""
    params = {
        "search": f'patient.drug.openfda.generic_name:"{escape_phrase(generic_name)}"',
        "count": "patient.reaction.reactionmeddrapt.exact",
        "limit": "1000",
    }
    if api_key:
        params["api_key"] = api_key
    try:
        response = http.get(FAERS_URL, params=params, timeout=30)
        if response.status_code != 200:
            return []
        return response.json().get("results", [])
    except httpx.HTTPError as error:
        print(f"    ! {generic_name} failed: {error}")
        return []


def main() -> None:
    load_dotenv()
    api_key = os.environ.get("OPENFDA_API_KEY")

    master = pd.read_csv(DATA_DIR / "drug_master.csv", dtype={"rxcui": str})
    unique_drugs = (
        master[["rxcui", "generic_name"]]
        .drop_duplicates(subset="rxcui")
        .sort_values("generic_name")
    )
    print(f"Querying FAERS for {len(unique_drugs)} drugs...\n")

    raw_rows = []
    side_effects_by_rxcui: dict[str, str] = {}

    with httpx.Client() as http:
        for i, (_, drug) in enumerate(unique_drugs.iterrows()):
            if i:
                time.sleep(DELAY)
            reactions = fetch_reactions(http, drug["generic_name"], api_key)

            effects = []
            for r in reactions:
                term = r.get("term", "")
                count = r.get("count", 0)
                raw_rows.append({
                    "rxcui": drug["rxcui"],
                    "generic_name": drug["generic_name"],
                    "reaction_term": term,
                    "report_count": count,
                })
                effects.append(term)

            side_effects_by_rxcui[drug["rxcui"]] = "; ".join(effects)

            if (i + 1) % 50 == 0:
                print(f"  {i + 1}/{len(unique_drugs)} drugs queried...")

    # Write raw per-reaction data
    raw_df = pd.DataFrame(raw_rows)
    raw_path = DATA_DIR / "faers_raw.csv"
    raw_df.to_csv(raw_path, index=False)

    # Add side effects column to master
    master["faers_side_effects"] = master["rxcui"].map(side_effects_by_rxcui).fillna("")
    master.to_csv(DATA_DIR / "drug_master.csv", index=False)

    drugs_with_data = sum(1 for v in side_effects_by_rxcui.values() if v)
    print(f"\nWrote {raw_path}")
    print(f"  Raw reactions: {len(raw_df)} rows")
    print(f"Updated drug_master.csv")
    print(f"  Drugs with FAERS data: {drugs_with_data}/{len(unique_drugs)}")
    print(f"  Drugs without FAERS data: {len(unique_drugs) - drugs_with_data}")


if __name__ == "__main__":
    main()
