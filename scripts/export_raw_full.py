"""Dump the FULL, unfiltered contents of the openFDA label and FAERS endpoints.

export_raw_api.py already dumps every RxClass class (raw_rxclass_pharmacology.csv
has all 12 class types) and the two label sections + reaction counts the pipeline
consumes. This script exists so you can evaluate source quality against
*everything* the openFDA endpoints return, not just the fields we keep:

  raw_openfda_labels_full.jsonl   one JSON line per drug = the ENTIRE label
                                  result (all ~27 SPL sections, verbatim)
  raw_openfda_label_sections.csv  which sections each drug's label has + their
                                  character counts (quick scan of coverage)
  raw_faers_facets.csv            per drug, every FAERS count facet beyond the
                                  reaction terms — seriousness, outcome, drug
                                  role (suspect vs concomitant), reporter type,
                                  sex — decoded to human-readable labels

The drug universe is read from the existing raw_openfda_labels.csv so this does
not re-derive it from RxClass.

Run: .venv/bin/python scripts/export_raw_full.py
"""

import json
import os
import time
from pathlib import Path

import httpx
import pandas as pd
from dotenv import load_dotenv

from med_graph.sources.lucene import escape_phrase

RAW_DIR = Path(__file__).resolve().parent.parent / "data_exports" / "raw"
LABEL_URL = "https://api.fda.gov/drug/label.json"
FAERS_URL = "https://api.fda.gov/drug/event.json"
DELAY = 0.2  # seconds between openFDA calls

# FAERS count facets (field -> friendly name) beyond the reaction terms already
# in raw_faers_reactions.csv. Each answers a "how trustworthy is this signal?"
# question the raw reaction counts alone can't.
FAERS_FACETS: dict[str, str] = {
    "serious": "serious_report",
    "seriousnessdeath": "outcome_death",
    "seriousnesshospitalization": "outcome_hospitalization",
    "seriousnesslifethreatening": "outcome_life_threatening",
    "patient.reaction.reactionoutcome": "reaction_outcome",
    "patient.drug.drugcharacterization": "drug_role",
    "primarysource.qualification": "reporter_type",
    "patient.patientsex": "patient_sex",
}

# Numeric FAERS code -> meaning, so the dump is readable without the data guide.
FAERS_CODES: dict[str, dict[str, str]] = {
    "serious": {"1": "serious", "2": "non-serious"},
    "seriousnessdeath": {"1": "yes", "2": "no"},
    "seriousnesshospitalization": {"1": "yes", "2": "no"},
    "seriousnesslifethreatening": {"1": "yes", "2": "no"},
    "patient.reaction.reactionoutcome": {
        "1": "recovered/resolved", "2": "recovering/resolving",
        "3": "not recovered/not resolved", "4": "recovered with sequelae",
        "5": "fatal", "6": "unknown",
    },
    "patient.drug.drugcharacterization": {
        "1": "suspect", "2": "concomitant", "3": "interacting", "4": "drug-not-administered",
    },
    "primarysource.qualification": {
        "1": "physician", "2": "pharmacist", "3": "other health professional",
        "4": "lawyer", "5": "consumer/non-health-professional",
    },
    "patient.patientsex": {"0": "unknown", "1": "male", "2": "female"},
}


def _get(http: httpx.Client, url: str, params: dict, api_key: str | None) -> dict | None:
    """GET returning parsed JSON, or None on any non-200 (so one drug can't abort)."""
    if api_key:
        params = {**params, "api_key": api_key}
    try:
        response = http.get(url, params=params, timeout=30)
        if response.status_code != 200:
            return None
        return response.json()
    except httpx.HTTPError as error:
        print(f"    ! {url} failed: {error}")
        return None


def dump_labels(http: httpx.Client, meds: list[dict], api_key: str | None,
                jsonl_path: Path) -> pd.DataFrame:
    """Write every drug's full label JSON to JSONL; return a section-coverage table."""
    section_rows = []
    with jsonl_path.open("w") as sink:
        for i, med in enumerate(meds):
            if i:
                time.sleep(DELAY)
            payload = _get(http, LABEL_URL, {
                "search": f'openfda.generic_name:"{escape_phrase(med["generic_name"])}"',
                "limit": "1",
            }, api_key)
            results = (payload or {}).get("results", [])
            result = results[0] if results else {}
            sink.write(json.dumps({
                "rxcui": med["rxcui"],
                "generic_name": med["generic_name"],
                "has_label": bool(results),
                "label": result,
            }) + "\n")
            for section, value in result.items():
                if section == "openfda":
                    continue
                text = " ".join(value) if isinstance(value, list) and value and isinstance(value[0], str) else ""
                if text:
                    section_rows.append({
                        "rxcui": med["rxcui"],
                        "generic_name": med["generic_name"],
                        "section": section,
                        "char_count": len(text),
                    })
            print(f"  label {i + 1}/{len(meds)}  {med['generic_name']}")
    return pd.DataFrame(section_rows)


def dump_faers_facets(http: httpx.Client, meds: list[dict], api_key: str | None) -> pd.DataFrame:
    """For each drug and facet, dump every category's report count (decoded)."""
    rows = []
    for i, med in enumerate(meds):
        for field, friendly in FAERS_FACETS.items():
            if i or field != next(iter(FAERS_FACETS)):
                time.sleep(DELAY)
            payload = _get(http, FAERS_URL, {
                "search": f'patient.drug.openfda.generic_name:"{escape_phrase(med["generic_name"])}"',
                "count": field,
                "limit": "20",
            }, api_key)
            if payload is None:
                continue
            codes = FAERS_CODES.get(field, {})
            for result in payload.get("results", []):
                term = str(result.get("term"))
                rows.append({
                    "rxcui": med["rxcui"],
                    "generic_name": med["generic_name"],
                    "facet": friendly,
                    "field": field,
                    "value": codes.get(term, term),
                    "report_count": result.get("count"),
                })
        print(f"  facets {i + 1}/{len(meds)}  {med['generic_name']}")
    return pd.DataFrame(rows)


def main() -> None:
    load_dotenv(str(Path(__file__).resolve().parent.parent / ".env"))
    api_key = os.environ.get("OPENFDA_API_KEY")
    universe = pd.read_csv(RAW_DIR / "raw_openfda_labels.csv", dtype={"rxcui": str})
    meds = universe[["rxcui", "generic_name"]].to_dict("records")
    print(f"Universe: {len(meds)} drugs (from raw_openfda_labels.csv)\n")

    with httpx.Client() as http:
        print("openFDA labels — full JSON (all sections)...")
        sections = dump_labels(http, meds, api_key, RAW_DIR / "raw_openfda_labels_full.jsonl")
        sections.to_csv(RAW_DIR / "raw_openfda_label_sections.csv", index=False)
        print(f"  raw_openfda_label_sections.csv  ({len(sections)} drug-section rows)\n")

        print("FAERS — all count facets (seriousness, outcome, drug role, reporter, sex)...")
        facets = dump_faers_facets(http, meds, api_key)
        facets.to_csv(RAW_DIR / "raw_faers_facets.csv", index=False)
        print(f"  raw_faers_facets.csv  ({len(facets)} rows)")

    print(f"\nDone. Full raw dumps in {RAW_DIR}")


if __name__ == "__main__":
    main()
