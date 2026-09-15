"""Build the candidate pool of symptom concepts from WHO ICD-11.

The symptom vocabulary is DERIVED, not hand-picked. This script produces the
pool it is derived from: ICD-11 Chapter 21 ("Symptoms, signs or clinical
findings"), which is WHO's own list -- no selection by us.

Two tiers, because not all of Chapter 21 is psychiatric:

  A  block MB2x, WHO's purpose-built psychiatric signs-and-symptoms block.
     Admitted unconditionally (141 leaf codes).
  B  the rest of Chapter 21 (671 leaf codes). Admitted only if a psychiatric
     disorder's ICD-11 CDDR diagnostic features actually reference it, which
     scripts/extract_cddr_symptoms.py decides. This is what pulls in the
     symptom-level sleep, fatigue and appetite codes (MG41, MG42, MG22,
     MG43.8/.9) without anyone hand-picking them.

Residual entries ("Other specified ...", "..., unspecified") are dropped: they
are classification plumbing, not concepts.

Licence: ICD-11 is CC BY-ND 3.0 IGO and permits commercial use. Section 1.2.3
requires that code, title and URI travel together, so all three are emitted.

Run: .venv/bin/python scripts/icd11_symptom_pool.py
Output: data_clean/symptom_pool.csv
"""

import io
import re
import zipfile
from pathlib import Path

import httpx
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
CACHE_DIR = REPO / "data_exports" / "raw"
CACHE = CACHE_DIR / "icd11_mms_simple_tabulation.txt"
OUT = REPO / "data_clean" / "symptom_pool.csv"

MMS_ZIP_URL = (
    "https://icdcdn.who.int/static/releasefiles/2025-01/"
    "SimpleTabulation-ICD-11-MMS-en.zip"
)
BROWSER_URL = "https://icd.who.int/browse/2025-01/mms/en#"
SYMPTOM_CHAPTER = "21"
PSYCHIATRIC_BLOCK = re.compile(r"^MB2")
RESIDUAL = re.compile(r"^Other specified|unspecified$", re.IGNORECASE)


def fetch_tabulation() -> Path:
    """Download WHO's simple tabulation once and cache it. No auth required."""
    if CACHE.exists():
        return CACHE
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        response = httpx.get(MMS_ZIP_URL, timeout=180, follow_redirects=True)
        response.raise_for_status()
        archive = zipfile.ZipFile(io.BytesIO(response.content))
    except httpx.HTTPError as error:
        raise SystemExit(f"Could not download the ICD-11 tabulation: {error}") from error
    except zipfile.BadZipFile as error:
        raise SystemExit(f"ICD-11 download was not a valid zip: {error}") from error

    names = [n for n in archive.namelist() if n.endswith(".txt")]
    if not names:
        raise SystemExit(f"No .txt found in {MMS_ZIP_URL}; contents: {archive.namelist()}")
    CACHE.write_bytes(archive.read(names[0]))
    return CACHE


def symptom_pool(tabulation: pd.DataFrame) -> pd.DataFrame:
    """Chapter 21 leaf concepts, tiered by whether they are the psychiatric block."""
    chapter = tabulation[
        (tabulation["ChapterNo"].astype(str) == SYMPTOM_CHAPTER)
        & (tabulation["isLeaf"].astype(str).str.lower() == "true")
    ].copy()
    chapter["title"] = chapter["Title"].astype(str).str.strip("- ").str.strip()
    concepts = chapter[~chapter["title"].str.contains(RESIDUAL, na=False)]

    is_psychiatric = concepts["Code"].astype(str).str.contains(PSYCHIATRIC_BLOCK, na=False)
    uri = concepts["Foundation URI"].astype(str)
    # The tabulation's own BrowserLink column is an Excel =hyperlink() formula,
    # which mangles the CSV. The browsable page is the entity id off the URI.
    entity_id = uri.str.rsplit("/", n=1).str[-1]
    return pd.DataFrame({
        "icd11_code": concepts["Code"].astype(str),
        "icd11_title": concepts["title"],
        "icd11_uri": uri,
        "browser_link": BROWSER_URL + entity_id,
        "pool_tier": is_psychiatric.map({True: "A", False: "B"}),
    }).sort_values(["pool_tier", "icd11_code"], ignore_index=True)


def main() -> None:
    tabulation = pd.read_csv(fetch_tabulation(), sep="\t", dtype=str, on_bad_lines="skip")
    pool = symptom_pool(tabulation)
    pool.to_csv(OUT, index=False)

    tier_a = int((pool.pool_tier == "A").sum())
    print(f"Wrote {OUT.relative_to(REPO)}")
    print(f"  {len(pool)} Chapter 21 leaf concepts")
    print(f"    tier A (MB2x, psychiatric, admitted unconditionally): {tier_a}")
    print(f"    tier B (rest of Chapter 21, admitted only via CDDR):  {len(pool) - tier_a}")


if __name__ == "__main__":
    main()
