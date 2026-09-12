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

# Why a drug has no openFDA label. Keyed by generic_name (lowercase).
NO_LABEL_REASON: dict[str, str] = {
    "aceprometazine": "Non-US",
    "acetanilide": "Obsolete",
    "acetophenazine": "Discontinued/Withdrawn",
    "aducanumab": "Discontinued/Withdrawn",
    "amobarbital": "Discontinued/Withdrawn",
    "anisindione": "Discontinued/Withdrawn",
    "aprobarbital": "Discontinued/Withdrawn",
    "belladonna alkaloids": "Obsolete",
    "belladonna extract, USP": "Obsolete",
    "belladonna leaf extract": "Obsolete",
    "benperidol": "Non-US",
    "brexanolone": "Discontinued/Withdrawn",
    "bromazepam": "Non-US",
    "bromodiphenhydramine": "Discontinued/Withdrawn",
    "bromperidol": "Non-US",
    "butabarbital": "Discontinued/Withdrawn",
    "butobarbital": "Non-US",
    "chlormethiazole": "Non-US",
    "chlormezanone": "Discontinued/Withdrawn",
    "chlorprothixene": "Discontinued/Withdrawn",
    "clopamide": "Non-US",
    "clotiazepam": "Non-US",
    "deserpidine": "Discontinued/Withdrawn",
    "dibenzepin": "Non-US",
    "dicumarol": "Obsolete",
    "digitoxin": "Discontinued/Withdrawn",
    "digoxin antibodies Fab fragments": "Combination ingredient",
    "dihydroergocornine": "Combination ingredient",
    "dihydroergocristine": "Combination ingredient",
    "dihydroergocryptine": "Combination ingredient",
    "dothiepin": "Non-US",
    "edetic acid": "Combination ingredient",
    "ergoloid mesylates, USP": "Discontinued/Withdrawn",
    "ethchlorvynol": "Discontinued/Withdrawn",
    "ethinamate": "Discontinued/Withdrawn",
    "flunitrazepam": "Non-US",
    "flupenthixol": "Non-US",
    "fluspirilene": "Non-US",
    "ginseng preparation": "Supplement/Natural",
    "glutethimide": "Discontinued/Withdrawn",
    "halazepam": "Discontinued/Withdrawn",
    "halofantrine": "Discontinued/Withdrawn",
    "huperzine A": "Supplement/Natural",
    "iron carbonyl": "Supplement/Natural",
    "kava preparation": "Supplement/Natural",
    "lesinurad": "Discontinued/Withdrawn",
    "levomethadyl": "Discontinued/Withdrawn",
    "lithium aspartate": "Supplement/Natural",
    "lormetazepam": "Non-US",
    "maprotiline": "Discontinued/Withdrawn",
    "mazindol": "Discontinued/Withdrawn",
    "mecobalamin": "Supplement/Natural",
    "medazepam": "Non-US",
    "mesoridazine": "Discontinued/Withdrawn",
    "mestranol": "Combination ingredient",
    "methaqualone": "Discontinued/Withdrawn",
    "methdilazine": "Discontinued/Withdrawn",
    "methotrimeprazine": "Discontinued/Withdrawn",
    "methyprylon": "Discontinued/Withdrawn",
    "nitrazepam": "Non-US",
    "nordazepam": "Non-US",
    "paraldehyde": "Obsolete",
    "pemoline": "Discontinued/Withdrawn",
    "penfluridol": "Non-US",
    "perazine": "Non-US",
    "pergolide": "Discontinued/Withdrawn",
    "periciazine": "Non-US",
    "phenmetrazine": "Discontinued/Withdrawn",
    "phenprocoumon": "Non-US",
    "pipamperone": "Non-US",
    "piperacetazine": "Discontinued/Withdrawn",
    "pipothiazine": "Non-US",
    "prazepam": "Discontinued/Withdrawn",
    "promazine": "Discontinued/Withdrawn",
    "propiomazine": "Discontinued/Withdrawn",
    "protamine sulfate (USP)": "Combination ingredient",
    "protamines": "Combination ingredient",
    "racemethionine": "Obsolete",
    "reboxetine": "Non-US",
    "reserpine": "Discontinued/Withdrawn",
    "secobarbital": "Discontinued/Withdrawn",
    "sertindole": "Non-US",
    "sibutramine": "Discontinued/Withdrawn",
    "somatrem": "Discontinued/Withdrawn",
    "tacrine": "Discontinued/Withdrawn",
    "tetrazepam": "Non-US",
    "theobromine": "Supplement/Natural",
    "thiamylal": "Discontinued/Withdrawn",
    "thiobutabarbital": "Non-US",
    "tibolone": "Non-US",
    "tocopheryl acid succinate,D-alpha": "Supplement/Natural",
    "tofisopam": "Non-US",
    "tricaprylin": "Combination ingredient",
    "trifluperidol": "Non-US",
    "triflupromazine": "Discontinued/Withdrawn",
    "trimeprazine": "Discontinued/Withdrawn",
    "valerian root extract": "Supplement/Natural",
    "yohimbine": "Supplement/Natural",
}


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
    df["no_label_reason"] = df.apply(
        lambda r: NO_LABEL_REASON.get(r["generic_name"], "") if not r["has_label"] else "",
        axis=1,
    )
    out_path = DATA_DIR / "openfda_labels.csv"
    df.to_csv(out_path, index=False)

    has_label = df[df.has_label]
    no_label = df[~df.has_label]
    has_match = df[df.matched_disorders != ""]
    print(f"\nWrote {out_path}")
    print(f"  Total drugs: {len(df)}")
    print(f"  With label: {len(has_label)}")
    print(f"  Without label: {len(no_label)}")
    print(f"  Product types: {has_label.product_type.value_counts().to_dict()}")
    print(f"  No-label reasons: {no_label.no_label_reason.value_counts().to_dict()}")
    print(f"  With matched psychiatric disorders: {len(has_match)}")


if __name__ == "__main__":
    main()
