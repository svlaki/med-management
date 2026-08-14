"""Pull all drugs under the MeSH "Mental Disorders" class tree from RxClass.

Produces two CSVs in data_clean/:

  1. tree_drug_conditions.csv  — walk the Mental Disorders class tree; for each
     subclass, fetch may_treat and may_prevent drug members. Only includes
     conditions within the Mental Disorders hierarchy.

  2. drug_all_conditions.csv   — take the unique drugs from step 1, then call
     the per-drug endpoint (class/byRxcui.json) to get ALL may_treat and
     may_prevent conditions each drug has, including non-psychiatric ones.

Run: .venv/bin/python scripts/export_rxnorm_classes.py
"""

import time
from pathlib import Path

import httpx
import pandas as pd

ROOT_CLASS = "D001523"  # MeSH "Mental Disorders"
TREE_URL = "https://rxnav.nlm.nih.gov/REST/rxclass/classTree.json"
MEMBERS_URL = "https://rxnav.nlm.nih.gov/REST/rxclass/classMembers.json"
BYRXCUI_URL = "https://rxnav.nlm.nih.gov/REST/rxclass/class/byRxcui.json"
OUT_DIR = Path(__file__).resolve().parent.parent / "data_clean"
ALL_RELAS = ("may_treat", "may_prevent", "ci_with")
DELAY = 0.03  # seconds between API calls


def collect_classes(nodes: list, depth: int, out: dict) -> None:
    """Recursively walk the rxclassTree and collect every class node."""
    for node in nodes:
        concept = node.get("rxclassMinConceptItem", {})
        class_id = concept.get("classId")
        if class_id and class_id not in out:
            out[class_id] = {
                "class_id": class_id,
                "class_name": concept.get("className"),
                "depth": depth,
            }
        collect_classes(node.get("rxclassTree", []) or [], depth + 1, out)


def fetch_members(http: httpx.Client, class_id: str, rela: str) -> list[dict]:
    """Fetch drug members for a class and relationship type."""
    response = http.get(
        MEMBERS_URL,
        params={
            "classId": class_id,
            "relaSource": "MEDRT",
            "rela": rela,
            "ttys": "IN",
        },
        timeout=30,
    )
    response.raise_for_status()
    members = response.json().get("drugMemberGroup", {}).get("drugMember", [])
    if isinstance(members, dict):
        members = [members]
    results = []
    for member in members:
        concept = member.get("minConcept", {})
        if concept.get("rxcui"):
            results.append({
                "rxcui": concept.get("rxcui"),
                "generic_name": concept.get("name"),
            })
    return results


def fetch_drug_conditions(http: httpx.Client, rxcui: str) -> list[dict]:
    """Fetch all DISEASE-class may_treat and may_prevent conditions for one drug."""
    response = http.get(BYRXCUI_URL, params={"rxcui": rxcui}, timeout=30)
    response.raise_for_status()
    info = (
        response.json()
        .get("rxclassDrugInfoList", {})
        .get("rxclassDrugInfo", [])
    )
    seen = set()
    results = []
    for item in info:
        concept = item.get("rxclassMinConceptItem", {})
        rela = item.get("rela")
        if concept.get("classType") == "DISEASE" and rela in ALL_RELAS:
            key = (concept.get("classId"), rela)
            if key not in seen:
                seen.add(key)
                results.append({
                    "class_id": concept.get("classId"),
                    "rela": rela,
                    "condition_name": concept.get("className"),
                })
    return results


def build_tree_table(http: httpx.Client, classes: dict) -> pd.DataFrame:
    """Table 1: walk the tree, fetch drug members per class."""
    rows = []
    call_count = 0
    for class_meta in classes.values():
        for rela in ALL_RELAS:
            if call_count:
                time.sleep(DELAY)
            call_count += 1
            drugs = fetch_members(http, class_meta["class_id"], rela)
            for drug in drugs:
                rows.append({
                    "class_id": class_meta["class_id"],
                    "rxcui": drug["rxcui"],
                    "generic_name": drug["generic_name"],
                    "rela": rela,
                    "condition_name": class_meta["class_name"],
                })
            if call_count % 80 == 0:
                print(f"  {call_count} API calls done...")
    df = pd.DataFrame(rows)
    df = df[df.condition_name != "Mental Disorders"]
    return df


def build_drug_table(http: httpx.Client, tree_df: pd.DataFrame) -> pd.DataFrame:
    """Table 2: for each unique drug from table 1, get ALL conditions via byRxcui."""
    unique_drugs = (
        tree_df[["rxcui", "generic_name"]]
        .drop_duplicates(subset="rxcui")
        .sort_values("generic_name")
    )
    rows = []
    for i, (_, drug) in enumerate(unique_drugs.iterrows()):
        if i:
            time.sleep(DELAY)
        conditions = fetch_drug_conditions(http, drug["rxcui"])
        for cond in conditions:
            rows.append({
                "class_id": cond["class_id"],
                "rxcui": drug["rxcui"],
                "generic_name": drug["generic_name"],
                "rela": cond["rela"],
                "condition_name": cond["condition_name"],
            })
        if (i + 1) % 50 == 0:
            print(f"  {i + 1}/{len(unique_drugs)} drugs queried...")
    return pd.DataFrame(rows)


def write_and_summarize(df: pd.DataFrame, path: Path, label: str) -> None:
    df = df.sort_values(["generic_name", "rela", "condition_name"])
    df.to_csv(path, index=False)
    print(f"\n{label}: {path.name}")
    print(f"  Total rows: {len(df)}")
    for rela in ALL_RELAS:
        subset = df[df.rela == rela]
        print(f"  {rela}: {len(subset)} rows")
    print(f"  Unique drugs: {df.rxcui.nunique()}")
    print(f"  Unique conditions: {df.condition_name.nunique()}")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    with httpx.Client() as http:
        print("Fetching Mental Disorders class tree...")
        tree = http.get(TREE_URL, params={"classId": ROOT_CLASS}, timeout=30).json()
        classes: dict[str, dict] = {}
        collect_classes(tree.get("rxclassTree", []), 0, classes)
        print(f"  {len(classes)} disease classes in taxonomy\n")

        print("Table 1: tree walk (Mental Disorders conditions only)...")
        tree_df = build_tree_table(http, classes)
        write_and_summarize(tree_df, OUT_DIR / "tree_drug_conditions.csv", "Table 1")

        print(f"\nTable 2: per-drug endpoint (all conditions for {tree_df.rxcui.nunique()} drugs)...")
        drug_df = build_drug_table(http, tree_df)
        write_and_summarize(drug_df, OUT_DIR / "drug_all_conditions.csv", "Table 2")

    print("\nDone.")


if __name__ == "__main__":
    main()
