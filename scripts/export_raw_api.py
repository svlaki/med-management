"""Pull the RAW, unfiltered source-API data into tables.

Separate from export_tables.py (which flattens the *processed* graph). This hits
RxClass, openFDA FAERS, and openFDA labels directly and dumps the full responses
so you can see everything before our pipeline filters/normalizes it:

  raw_rxclass_members.csv  every may_treat member per condition class (RxClass)
  raw_faers_reactions.csv  EVERY FAERS reaction term + count per drug (unfiltered;
                           the graph keeps only the top ~20 after dropping
                           administrative terms)
  raw_openfda_labels.csv   full indications_and_usage + adverse_reactions text
                           per drug (the graph keeps only derived flags)

Run: .venv/bin/python scripts/export_raw_api.py
"""

import time
from pathlib import Path

import httpx
import pandas as pd
from dotenv import load_dotenv

from med_graph.sources.lucene import escape_phrase

OUT_DIR = Path(__file__).resolve().parent.parent / "data_exports" / "raw"
RXCLASS_URL = "https://rxnav.nlm.nih.gov/REST/rxclass/classMembers.json"
FAERS_URL = "https://api.fda.gov/drug/event.json"
LABEL_URL = "https://api.fda.gov/drug/label.json"
DELAY = 0.25  # seconds between openFDA calls (anonymous rate limit is 240/min)

# Core psychiatric MeSH disease classes whose may_treat members define the drug
# universe (covers antidepressants, antipsychotics, anxiolytics, sedative-
# hypnotics, stimulants, and mood stabilizers). Broad on purpose; the ATC-derived
# drug_class in the aggregation marks anything non-psychiatric as "Other".
CORE_PSYCH_CLASSES: list[tuple[str, str]] = [
    ("D003866", "Depressive Disorder"),
    ("D000068105", "Bipolar and Related Disorders"),
    ("D001008", "Anxiety Disorders"),
    ("D019967", "Schizophrenia Spectrum and Other Psychotic Disorders"),
    ("D019958", "Attention Deficit and Disruptive Behavior Disorders"),
    ("D007319", "Sleep Initiation and Maintenance Disorders"),
    ("D009771", "Obsessive-Compulsive Disorder"),
    ("D016584", "Panic Disorder"),
    ("D013313", "Stress Disorders, Post-Traumatic"),
]


class ApiKeyRequired(Exception):
    """openFDA rejected the request for lack of an api_key (anonymous quota)."""


def _get(http: httpx.Client, url: str, params: dict) -> dict | None:
    """GET returning parsed JSON, or None on 404/error (so one drug can't abort)."""
    try:
        response = http.get(url, params=params, timeout=30)
        if response.status_code == 404:
            return None
        if response.status_code == 403 and "api_key" in response.text.lower():
            raise ApiKeyRequired(
                "openFDA returned 403 (anonymous daily quota exhausted or key "
                "required). Get a free key at https://open.fda.gov/apis/authentication/ "
                "and add OPENFDA_API_KEY=... to .env, then re-run."
            )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as error:
        print(f"    ! {url} failed: {error}")
        return None


def _class_members(http: httpx.Client, class_id: str) -> list[dict]:
    payload = _get(
        http,
        RXCLASS_URL,
        {"classId": class_id, "relaSource": "MEDRT", "rela": "may_treat", "ttys": "IN"},
    )
    members = (payload or {}).get("drugMemberGroup", {}).get("drugMember", [])
    return [members] if isinstance(members, dict) else members


def rxclass_members(http: httpx.Client) -> pd.DataFrame:
    rows = []
    for class_id, class_name in CORE_PSYCH_CLASSES:
        for member in _class_members(http, class_id):
            concept = member.get("minConcept", {})
            rows.append({
                "rxclass_id": class_id,
                "class_name": class_name,
                "rxcui": concept.get("rxcui"),
                "generic_name": concept.get("name"),
                "tty": concept.get("tty"),
            })
    return pd.DataFrame(rows)


def psych_universe(http: httpx.Client) -> list[dict]:
    """Distinct drugs across the core psychiatric classes, deduped by rxcui."""
    by_rxcui: dict[str, dict] = {}
    for class_id, _ in CORE_PSYCH_CLASSES:
        for member in _class_members(http, class_id):
            concept = member.get("minConcept", {})
            rxcui = concept.get("rxcui")
            if rxcui and rxcui not in by_rxcui:
                by_rxcui[rxcui] = {"rxcui": rxcui, "generic_name": concept.get("name")}
    return sorted(by_rxcui.values(), key=lambda m: m["generic_name"] or "")


def faers_reactions(http: httpx.Client, meds: list[dict], api_key: str | None) -> pd.DataFrame:
    rows = []
    for i, med in enumerate(meds):
        if i:
            time.sleep(DELAY)
        params = {
            "search": f'patient.drug.openfda.generic_name:"{escape_phrase(med["generic_name"])}"',
            "count": "patient.reaction.reactionmeddrapt.exact",
            "limit": "1000",
        }
        if api_key:
            params["api_key"] = api_key
        payload = _get(http, FAERS_URL, params)
        for result in (payload or {}).get("results", []):
            rows.append({
                "rxcui": med["rxcui"],
                "generic_name": med["generic_name"],
                "reaction_term": result.get("term"),
                "report_count": result.get("count"),
            })
        print(f"  FAERS {i + 1}/{len(meds)}  {med['generic_name']}")
    return pd.DataFrame(rows)


def openfda_labels(http: httpx.Client, meds: list[dict], api_key: str | None) -> pd.DataFrame:
    rows = []
    for i, med in enumerate(meds):
        if i:
            time.sleep(DELAY)
        params = {
            "search": f'openfda.generic_name:"{escape_phrase(med["generic_name"])}"',
            "limit": "1",
        }
        if api_key:
            params["api_key"] = api_key
        payload = _get(http, LABEL_URL, params)
        results = (payload or {}).get("results", [])
        result = results[0] if results else {}
        rows.append({
            "rxcui": med["rxcui"],
            "generic_name": med["generic_name"],
            "has_label": bool(results),
            "indications_and_usage": " ".join(result.get("indications_and_usage", [])),
            "adverse_reactions": " ".join(result.get("adverse_reactions", [])),
        })
        print(f"  label {i + 1}/{len(meds)}  {med['generic_name']}")
    return pd.DataFrame(rows)


def _truncate_for_excel(df: pd.DataFrame) -> pd.DataFrame:
    """Excel caps a cell at 32,767 chars; truncate long free-text for the workbook."""
    limit = 32000
    out = df.copy()
    for col in out.columns:
        if out[col].dtype == object:
            out[col] = out[col].map(
                lambda v: v[:limit] + "…[truncated]" if isinstance(v, str) and len(v) > limit else v
            )
    return out


def main() -> None:
    import os

    load_dotenv()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    api_key = os.environ.get("OPENFDA_API_KEY")

    with httpx.Client() as http:
        print("RxClass members + psychiatric drug universe...")
        frames = {"raw_rxclass_members": rxclass_members(http)}
        meds = psych_universe(http)
        print(f"  universe: {len(meds)} distinct drugs")
        print("openFDA label full text...")
        frames["raw_openfda_labels"] = openfda_labels(http, meds, api_key)
        print("FAERS raw reaction counts (unfiltered)...")
        try:
            frames["raw_faers_reactions"] = faers_reactions(http, meds, api_key)
        except ApiKeyRequired as error:
            print(f"\n  SKIPPED FAERS: {error}\n")

    for name, df in frames.items():
        df.to_csv(OUT_DIR / f"{name}.csv", index=False)
        print(f"  {name}.csv  ({len(df)} rows)")

    with pd.ExcelWriter(OUT_DIR / "med_graph_raw_api.xlsx") as writer:
        for name, df in frames.items():
            _truncate_for_excel(df).to_excel(writer, sheet_name=name[:31], index=False)

    print(f"\nDone. Raw tables in {OUT_DIR}")


if __name__ == "__main__":
    main()
