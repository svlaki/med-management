"""Enumerate every psychiatric disorder in RxClass and how many drugs it has.

Walks the MeSH "Mental Disorders" (D001523) subtree that RxClass exposes and, for
each disease class, counts its `may_treat` members (MED-RT, ingredient-level) —
i.e. how many medications RxClass links to it. Populated classes are the ones we
could actually build a condition from; the rest exist in the taxonomy but have no
drugs.

Run: .venv/bin/python scripts/psychiatric_disorders.py
Output: data_exports/psychiatric_disorders.csv
"""

import time
from pathlib import Path

import httpx
import pandas as pd

ROOT_CLASS = "D001523"  # MeSH "Mental Disorders"
TREE_URL = "https://rxnav.nlm.nih.gov/REST/rxclass/classTree.json"
MEMBERS_URL = "https://rxnav.nlm.nih.gov/REST/rxclass/classMembers.json"
OUT = Path(__file__).resolve().parent.parent / "data_exports" / "psychiatric_disorders.csv"


def collect_classes(nodes: list, depth: int, out: dict) -> None:
    for node in nodes:
        concept = node.get("rxclassMinConceptItem", {})
        class_id = concept.get("classId")
        if class_id and class_id not in out:
            out[class_id] = {"class_id": class_id, "class_name": concept.get("className"), "depth": depth}
        collect_classes(node.get("rxclassTree", []) or [], depth + 1, out)


def member_count(http: httpx.Client, class_id: str) -> tuple[int, list[str]]:
    r = http.get(
        MEMBERS_URL,
        params={"classId": class_id, "relaSource": "MEDRT", "rela": "may_treat", "ttys": "IN"},
        timeout=30,
    )
    r.raise_for_status()
    members = r.json().get("drugMemberGroup", {}).get("drugMember", [])
    if isinstance(members, dict):
        members = [members]
    names = sorted({m.get("minConcept", {}).get("name") for m in members if m.get("minConcept")})
    return len(names), names


def main() -> None:
    with httpx.Client() as http:
        tree = http.get(TREE_URL, params={"classId": ROOT_CLASS}, timeout=30).json()
        classes: dict[str, dict] = {}
        collect_classes(tree.get("rxclassTree", []), 0, classes)
        print(f"{len(classes)} psychiatric disease classes in the taxonomy; counting drugs...")

        rows = []
        for i, meta in enumerate(classes.values()):
            count, names = member_count(http, meta["class_id"])
            rows.append({**meta, "drug_count": count, "example_drugs": ", ".join(names[:6])})
            if i % 40 == 0:
                print(f"  {i}/{len(classes)}")
            time.sleep(0.03)

    df = pd.DataFrame(rows).sort_values(["drug_count", "class_name"], ascending=[False, True])
    # Explicit flag for whether RxClass lists any drugs for the class.
    df["drug_status"] = df["drug_count"].map(lambda n: "populated" if n > 0 else "empty")
    df = df[["class_id", "class_name", "depth", "drug_status", "drug_count", "example_drugs"]]
    OUT.parent.mkdir(exist_ok=True)
    df.to_csv(OUT, index=False)

    populated = df[df.drug_count > 0]
    print(f"\n{len(populated)} of {len(df)} classes have drugs. Populated psychiatric disorders:\n")
    print(populated[["class_id", "class_name", "drug_count"]].to_string(index=False))
    print(f"\nFull table (incl. empty classes): {OUT}")


if __name__ == "__main__":
    main()
