"""Match ICD-11 symptom concepts against the CDDR's diagnostic feature text.

This answers "which symptoms does the CDDR say belong to this disorder?", which
feeds two things: rule 1 of the derived symptom vocabulary, and the eventual
disorder -> symptom edges. Both then cite a WHO page rather than our judgment.

Matching is deliberately conservative:

  * Only symptom-bearing sections count. "Boundaries with other disorders" is
    differential-diagnosis prose that name-drops other disorders' symptoms, so
    including it would link nearly every symptom to nearly every disorder.
  * Titles are normalised for British/American spelling (the CDDR mixes them --
    "behaviour" 251 times, "disorganized" 6) and for classification qualifiers
    like ", not elsewhere classified" that never appear in running text.
  * Genuine wording differences are handled by data_clean/symptom_synonyms.csv,
    not by loosening the matcher. That file is the one place this step's
    judgment lives, and it is meant to be edited.

Run: .venv/bin/python scripts/match_cddr_symptoms.py
Output: data_clean/cddr_symptom_matches.csv
"""

import re
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "data_clean"
POOL = DATA / "symptom_pool.csv"
FEATURES = DATA / "cddr_disorder_features.csv"
SYNONYMS = DATA / "symptom_synonyms.csv"
OUT = DATA / "cddr_symptom_matches.csv"

# Sections that describe what a disorder IS. Everything else in the CDDR either
# distinguishes it from something else or describes its course and context.
SYMPTOM_SECTIONS = frozenset({
    "Essential (required) features",
    "Additional clinical features",
    "(unsectioned)",
})

# Classification plumbing that appears in titles but never in prose.
QUALIFIERS = re.compile(r",?\s*not elsewhere classified|\s*\(disorder\)", re.IGNORECASE)


def normalise(text: str) -> str:
    """Fold spelling variants so an ICD-11 title can match CDDR running text."""
    lowered = QUALIFIERS.sub("", text.lower())
    lowered = re.sub(r"isation\b", "ization", lowered)
    lowered = re.sub(r"ised\b", "ized", lowered)
    lowered = re.sub(r"ise\b", "ize", lowered)
    lowered = lowered.replace("behaviour", "behavior").replace("oe", "e")
    return re.sub(r"\s+", " ", lowered).strip()


def surface_forms(pool: pd.DataFrame, synonyms: pd.DataFrame) -> dict[str, set[str]]:
    """Every string that should count as a mention of each concept."""
    forms = {row.icd11_code: {normalise(row.icd11_title)} for row in pool.itertuples()}
    for row in synonyms.itertuples():
        if row.icd11_code in forms:
            forms[row.icd11_code].add(normalise(row.synonym))
    return forms


def mentions(form: str, text: str) -> bool:
    """Whole-word match, tolerating a trailing plural on the final word."""
    stem = re.sub(r"(s|es)$", "", form)
    return re.search(rf"\b{re.escape(stem)}(s|es)?\b", text) is not None


def match(features: pd.DataFrame, forms: dict[str, set[str]]) -> pd.DataFrame:
    """One row per (disorder, symptom) the CDDR text supports."""
    rows = []
    for feature in features.itertuples():
        text = normalise(str(feature.feature))
        for code, variants in forms.items():
            matched = next((v for v in variants if mentions(v, text)), None)
            if matched:
                rows.append({
                    "disorder_icd11_code": feature.icd11_code,
                    "disorder_title": feature.disorder_title,
                    "symptom_icd11_code": code,
                    "matched_form": matched,
                    "section": feature.section,
                    "cddr_page": feature.cddr_page,
                })
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    return frame.drop_duplicates(
        subset=["disorder_icd11_code", "symptom_icd11_code"], keep="first"
    ).sort_values(["disorder_icd11_code", "symptom_icd11_code"], ignore_index=True)


def read(path: Path) -> pd.DataFrame:
    try:
        return pd.read_csv(path, dtype=str)
    except FileNotFoundError as error:
        raise SystemExit(
            f"{path.name} not found. Run scripts/icd11_symptom_pool.py and "
            f"scripts/extract_cddr_symptoms.py first."
        ) from error


def main() -> None:
    pool = read(POOL)
    features = read(FEATURES)
    synonyms = read(SYNONYMS)

    usable = features[features.section.isin(SYMPTOM_SECTIONS)]
    matches = match(usable, surface_forms(pool, synonyms))
    matches.to_csv(OUT, index=False)

    tiers = pool.set_index("icd11_code").pool_tier
    matched_codes = set(matches.symptom_icd11_code)
    print(f"Wrote {OUT.relative_to(REPO)}")
    print(f"  {len(usable)} of {len(features)} feature rows used "
          f"(symptom-bearing sections only)")
    print(f"  {len(matches)} disorder-symptom pairs, "
          f"{len(matched_codes)} distinct symptoms, "
          f"{matches.disorder_icd11_code.nunique()} distinct disorders")
    for tier in ("A", "B"):
        in_tier = set(tiers[tiers == tier].index)
        print(f"    tier {tier}: {len(matched_codes & in_tier)} of {len(in_tier)} matched")


if __name__ == "__main__":
    main()
