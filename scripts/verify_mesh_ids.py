"""Verify the mesh_id column of data_clean/symptoms.csv against NLM MeSH.

The symptom vocabulary is hand-curated, so its MeSH ids are hand-written and must
not be trusted. This resolves every non-blank mesh_id against the NLM MeSH lookup
API and writes the authoritative preferred term into the mesh_term column, so the
file records both what we call a symptom and what MeSH calls it.

Two outcomes are treated very differently:

  * an id that does not resolve is simply wrong, and is BLANKED.
  * an id that resolves to a differently-worded term is REPORTED, not blanked.
    Our names are deliberately readable where MeSH uses a clinical noun -- we say
    "Low energy", MeSH says "Fatigue" -- so a wording difference is expected and
    only a human can judge whether the concepts actually match.

A blank mesh_id is a valid curation outcome: several psychiatric symptom domains
(emotional blunting, disorganization, inattention) have no MeSH descriptor. For
those rows this reports an exact-label match if MeSH happens to have one, but
never adopts it -- that is a curation decision.

Run: .venv/bin/python scripts/verify_mesh_ids.py          (report only)
     .venv/bin/python scripts/verify_mesh_ids.py --write  (apply terms, drop bad ids)
"""

import argparse
from pathlib import Path

import httpx
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
SYMPTOMS = REPO / "data_clean" / "symptoms.csv"

DETAILS_URL = "https://id.nlm.nih.gov/mesh/lookup/details"
DESCRIPTOR_URL = "https://id.nlm.nih.gov/mesh/lookup/descriptor"


def preferred_term(http: httpx.Client, mesh_id: str) -> str | None:
    """The preferred MeSH term for a descriptor id, or None if it does not resolve.

    An unknown id still returns HTTP 200, just with an empty `terms` list, so the
    status code alone cannot be trusted.
    """
    try:
        response = http.get(DETAILS_URL, params={"descriptor": mesh_id}, timeout=30)
        response.raise_for_status()
        terms = response.json().get("terms", [])
    except (httpx.HTTPError, ValueError) as error:
        raise SystemExit(f"MeSH lookup failed for {mesh_id}: {error}") from error
    return next((t["label"] for t in terms if t.get("preferred")), None)


def exact_match(http: httpx.Client, name: str) -> str | None:
    """A descriptor id whose label exactly matches `name`, if MeSH has one."""
    try:
        response = http.get(
            DESCRIPTOR_URL, params={"label": name, "match": "exact"}, timeout=30
        )
        response.raise_for_status()
        hits = response.json()
    except (httpx.HTTPError, ValueError):
        return None
    if not hits:
        return None
    return str(hits[0].get("resource", "")).rsplit("/", 1)[-1] or None


def resolve(http: httpx.Client, symptoms: pd.DataFrame) -> tuple[dict, dict, list]:
    """Return (id -> mesh_id kept, id -> authoritative term, rows needing review)."""
    kept: dict[str, str] = {}
    terms: dict[str, str] = {}
    review: list[tuple[str, str, str, str]] = []

    for _, row in symptoms.iterrows():
        symptom_id, name = row["id"], row["name"]
        mesh_id = row["mesh_id"].strip()

        if not mesh_id:
            suggestion = exact_match(http, name)
            hint = f"   MeSH has an exact match: {suggestion}" if suggestion else ""
            print(f"  blank    {symptom_id:24s} {name}{hint}")
            continue

        term = preferred_term(http, mesh_id)
        if term is None:
            print(f"  DROPPED  {symptom_id:24s} {mesh_id} does not resolve")
            continue

        kept[symptom_id] = mesh_id
        terms[symptom_id] = term
        if term.casefold() != name.casefold():
            review.append((symptom_id, mesh_id, name, term))
            print(f"  review   {symptom_id:24s} {mesh_id}  we say {name!r}, MeSH {term!r}")
        else:
            print(f"  ok       {symptom_id:24s} {mesh_id}  {term}")

    return kept, terms, review


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write",
        action="store_true",
        help="write resolved terms into mesh_term and drop ids that do not resolve",
    )
    args = parser.parse_args()

    try:
        symptoms = pd.read_csv(SYMPTOMS, dtype=str).fillna("")
    except FileNotFoundError as error:
        raise SystemExit(f"{SYMPTOMS} not found.") from error

    with httpx.Client() as http:
        kept, terms, review = resolve(http, symptoms)

    blank = int((symptoms.mesh_id.str.strip() == "").sum())
    dropped = len(symptoms) - len(kept) - blank
    print(
        f"\n{len(kept)} resolved ({len(review)} worded differently and needing a look), "
        f"{dropped} dropped as unresolvable, {blank} blank by curation"
    )
    if review:
        print("A wording difference is expected -- confirm each names the same concept.")

    if not args.write:
        print("\nReport only. Re-run with --write to apply.")
        return

    updated = symptoms.assign(
        mesh_id=symptoms["id"].map(kept).fillna(""),
        mesh_term=symptoms["id"].map(terms).fillna(""),
    )
    updated.to_csv(SYMPTOMS, index=False)
    print(f"Wrote {SYMPTOMS.relative_to(REPO)}")


if __name__ == "__main__":
    main()
