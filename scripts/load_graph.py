"""Load the clean dataset into Neo4j with the Option C graph schema.

Reads drug_master.csv, faers_raw.csv, drug_classes.csv, and
tree_drug_conditions.csv from data_clean/ and builds a graph of exactly three
node types: Drug, Condition (a psychiatric disorder), and SideEffect. DrugClass
nodes exist only to back the frontend's class filter; they are never drawn.

Scope, in one sentence: psychiatric drugs, the disorders they treat, and the
side effects reported for them.

  * A Condition is loaded only if it is a psychiatric disorder — a MeSH
    "Mental Disorders" (D001523) class, per tree_drug_conditions.csv, plus the
    symptom-level terms in PSYCHIATRIC_SYMPTOM_TERMS that MeSH files elsewhere.
    Indications like Anemia or Atrial Fibrillation are dropped.
  * A Drug is loaded only if it may treat or may prevent one of those
    disorders. That drops both non-psychiatric drugs RxClass returns because
    they are merely contraindicated against a psychiatric condition
    (amiodarone, furosemide, oral contraceptives) and tree artefacts with no
    therapeutic link (somatropin, idursulfase).
  * Contraindications (ci_with) are not loaded at all.

Because drugs and disorders are derived from the same edge set, no node can end
up isolated.

Run: .venv/bin/python scripts/load_graph.py
Requires: Neo4j running (docker compose up -d neo4j)
"""

from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from med_graph.graph.client import GraphClient
from med_graph.models.slug import slugify

DATA_DIR = Path(__file__).resolve().parent.parent / "data_clean"

# --- Cypher templates ---

CLEAR_GRAPH = "MATCH (n) DETACH DELETE n"

MERGE_DRUG_CLASSES = """
UNWIND $rows AS row
MERGE (dc:DrugClass {id: row.id})
SET dc.name = row.name
"""

MERGE_DRUGS = """
UNWIND $rows AS row
MERGE (d:Drug {rxcui: row.rxcui})
SET d.generic_name = row.generic_name,
    d.has_label = row.has_label,
    d.product_type = row.product_type
"""

MERGE_CONDITIONS = """
UNWIND $rows AS row
MERGE (c:Condition {id: row.id})
SET c.name = row.name
"""

MERGE_SIDE_EFFECTS = """
UNWIND $rows AS row
MERGE (s:SideEffect {id: row.id})
SET s.name = row.name, s.meddra_term = row.meddra_term
"""

MERGE_MAY_TREAT = """
UNWIND $rows AS row
MATCH (d:Drug {rxcui: row.rxcui})
MATCH (c:Condition {id: row.condition_id})
MERGE (d)-[:MAY_TREAT]->(c)
"""

MERGE_MAY_PREVENT = """
UNWIND $rows AS row
MATCH (d:Drug {rxcui: row.rxcui})
MATCH (c:Condition {id: row.condition_id})
MERGE (d)-[:MAY_PREVENT]->(c)
"""

MERGE_HAS_SIDE_EFFECT = """
UNWIND $rows AS row
MATCH (d:Drug {rxcui: row.rxcui})
MATCH (s:SideEffect {id: row.side_effect_id})
MERGE (d)-[r:HAS_SIDE_EFFECT]->(s)
SET r.report_count = row.report_count
"""

MERGE_BELONGS_TO = """
UNWIND $rows AS row
MATCH (d:Drug {rxcui: row.rxcui})
MATCH (dc:DrugClass {id: row.drug_class_id})
MERGE (d)-[:BELONGS_TO]->(dc)
"""

# Therapeutic relationships only. A ci_with link means the opposite of treating
# a disorder, so contraindications are excluded from the graph entirely.
EDGE_QUERIES = {
    "may_treat": MERGE_MAY_TREAT,
    "may_prevent": MERGE_MAY_PREVENT,
}

# Psychiatric targets that MeSH classifies as symptoms or behaviours rather than
# under "Mental Disorders", so the class tree alone would miss them. Without
# these the graph has no plain "Depression" or "Anxiety" node.
PSYCHIATRIC_SYMPTOM_TERMS = frozenset({
    "Aggression",
    "Anxiety",
    "Bulimia",
    "Catatonia",
    "Mania",
    "Psychomotor Agitation",
    "Psychophysiologic Disorders",
    "Sleep Apnea, Obstructive",
})

# Map informal condition names to their canonical disorder name so that e.g.
# drugs listed under "Depression" merge into the "Depressive Disorder" node.
CONDITION_ALIASES: dict[str, str] = {
    "Depression": "Depressive Disorder",
}


def disorder_vocabulary(tree_df: pd.DataFrame) -> frozenset[str]:
    """Condition names that count as psychiatric disorders.

    tree_drug_conditions.csv is a walk of the MeSH "Mental Disorders" subtree,
    so every condition name in it is a psychiatric class by construction.
    """
    return frozenset(tree_df["condition_name"].dropna()) | PSYCHIATRIC_SYMPTOM_TERMS


def therapeutic_edges(
    master_df: pd.DataFrame, vocabulary: frozenset[str]
) -> pd.DataFrame:
    """One row per drug -> psychiatric disorder link.

    `condition_name` in drug_master.csv holds "; "-joined names, so cells are
    expanded and then filtered to the disorder vocabulary. Drugs and conditions
    are both derived from the result, which is what keeps the graph free of
    isolated nodes.
    """
    rows = []
    for _, record in master_df[master_df["rela"].isin(EDGE_QUERIES)].iterrows():
        cell = record["condition_name"]
        if not isinstance(cell, str):
            continue
        for raw_name in (part.strip() for part in cell.split("; ")):
            name = CONDITION_ALIASES.get(raw_name, raw_name)
            if name in vocabulary:
                rows.append(
                    {
                        "rxcui": record["rxcui"],
                        "rela": record["rela"],
                        "condition_name": name,
                    }
                )
    return pd.DataFrame(rows, columns=["rxcui", "rela", "condition_name"])


def load_drug_classes(client: GraphClient, classes_df: pd.DataFrame) -> int:
    """Create DrugClass nodes from distinct drug_class values."""
    distinct = classes_df["drug_class"].dropna().unique()
    rows = [{"id": slugify(name), "name": name} for name in sorted(distinct)]
    client.execute(MERGE_DRUG_CLASSES, {"rows": rows})
    return len(rows)


def load_drugs(client: GraphClient, master_df: pd.DataFrame) -> int:
    """Create Drug nodes from unique drugs in master."""
    unique = master_df.drop_duplicates(subset="rxcui")
    rows = [
        {
            "rxcui": r["rxcui"],
            "generic_name": r["generic_name"],
            "has_label": bool(r["has_label"]),
            "product_type": r["product_type"] if isinstance(r["product_type"], str) else "",
        }
        for _, r in unique.iterrows()
    ]
    client.execute(MERGE_DRUGS, {"rows": rows})
    return len(rows)


def load_conditions(client: GraphClient, edges_df: pd.DataFrame) -> int:
    """Create a Condition node for each psychiatric disorder that has an edge."""
    names = sorted(set(edges_df["condition_name"]))
    rows = [{"id": slugify(name), "name": name} for name in names]
    client.execute(MERGE_CONDITIONS, {"rows": rows})
    return len(rows)


def load_side_effects(client: GraphClient, faers_df: pd.DataFrame) -> int:
    """Create SideEffect nodes from unique FAERS reaction terms."""
    unique = faers_df["reaction_term"].dropna().unique()
    rows = [
        {"id": slugify(term), "name": term, "meddra_term": term}
        for term in sorted(unique)
    ]
    # Batch in chunks to avoid huge transactions
    chunk_size = 5000
    for i in range(0, len(rows), chunk_size):
        client.execute(MERGE_SIDE_EFFECTS, {"rows": rows[i:i + chunk_size]})
    return len(rows)


def load_condition_edges(client: GraphClient, edges_df: pd.DataFrame) -> dict[str, int]:
    """Create MAY_TREAT and MAY_PREVENT edges."""
    counts = {}
    for rela, query in EDGE_QUERIES.items():
        rows = [
            {"rxcui": record["rxcui"], "condition_id": slugify(record["condition_name"])}
            for _, record in edges_df[edges_df["rela"] == rela].iterrows()
        ]
        if rows:
            client.execute(query, {"rows": rows})
        counts[rela] = len(rows)
    return counts


def load_side_effect_edges(client: GraphClient, faers_df: pd.DataFrame) -> int:
    """Create HAS_SIDE_EFFECT edges with report_count."""
    rows = [
        {
            "rxcui": str(r["rxcui"]),
            "side_effect_id": slugify(r["reaction_term"]),
            "report_count": int(r["report_count"]),
        }
        for _, r in faers_df.iterrows()
        if isinstance(r["reaction_term"], str)
    ]
    chunk_size = 5000
    for i in range(0, len(rows), chunk_size):
        client.execute(MERGE_HAS_SIDE_EFFECT, {"rows": rows[i:i + chunk_size]})
    return len(rows)


def load_belongs_to(client: GraphClient, classes_df: pd.DataFrame) -> int:
    """Create BELONGS_TO edges from drug to drug class."""
    rows = [
        {"rxcui": r["rxcui"], "drug_class_id": slugify(r["drug_class"])}
        for _, r in classes_df.iterrows()
        if isinstance(r["drug_class"], str)
    ]
    client.execute(MERGE_BELONGS_TO, {"rows": rows})
    return len(rows)


def main() -> None:
    load_dotenv()

    print("Reading data files...")
    master = pd.read_csv(DATA_DIR / "drug_master.csv", dtype={"rxcui": str})
    faers = pd.read_csv(DATA_DIR / "faers_raw.csv", dtype={"rxcui": str})
    classes = pd.read_csv(DATA_DIR / "drug_classes.csv", dtype={"rxcui": str})
    tree = pd.read_csv(DATA_DIR / "tree_drug_conditions.csv", dtype={"rxcui": str})

    vocabulary = disorder_vocabulary(tree)
    edges = therapeutic_edges(master, vocabulary)
    psychiatric = set(edges["rxcui"])

    dropped = master[~master.rxcui.isin(psychiatric)].drop_duplicates("rxcui")
    master = master[master.rxcui.isin(psychiatric)]
    faers = faers[faers.rxcui.isin(psychiatric)]
    classes = classes[classes.rxcui.isin(psychiatric)]
    print(
        f"  {len(psychiatric)} psychiatric drugs kept, "
        f"{len(dropped)} dropped (e.g. {', '.join(sorted(dropped.generic_name)[:3])})"
    )
    print(f"  {edges.condition_name.nunique()} psychiatric disorders in scope")

    with GraphClient.from_env() as client:
        print("Clearing existing graph...")
        client.execute(CLEAR_GRAPH)

        print("Applying schema constraints...")
        client.apply_schema()

        print("Loading DrugClass nodes...")
        n = load_drug_classes(client, classes)
        print(f"  {n} DrugClass nodes")

        print("Loading Drug nodes...")
        n = load_drugs(client, master)
        print(f"  {n} Drug nodes")

        print("Loading Condition nodes...")
        n = load_conditions(client, edges)
        print(f"  {n} Condition nodes")

        print("Loading SideEffect nodes...")
        n = load_side_effects(client, faers)
        print(f"  {n} SideEffect nodes")

        print("Loading condition edges (MAY_TREAT, MAY_PREVENT)...")
        counts = load_condition_edges(client, edges)
        for rela, count in counts.items():
            print(f"  {rela}: {count} edges")

        print("Loading HAS_SIDE_EFFECT edges...")
        n = load_side_effect_edges(client, faers)
        print(f"  {n} HAS_SIDE_EFFECT edges")

        print("Loading BELONGS_TO edges...")
        n = load_belongs_to(client, classes)
        print(f"  {n} BELONGS_TO edges")

        # Verification counts
        print("\n--- Verification ---")
        for label in ["Drug", "Condition", "SideEffect", "DrugClass"]:
            result = client.execute(f"MATCH (n:{label}) RETURN count(n) AS c")
            print(f"  {label}: {result[0]['c']} nodes")
        for rel in ["MAY_TREAT", "MAY_PREVENT", "HAS_SIDE_EFFECT", "BELONGS_TO"]:
            result = client.execute(f"MATCH ()-[r:{rel}]->() RETURN count(r) AS c")
            print(f"  {rel}: {result[0]['c']} edges")

    print("\nDone.")


if __name__ == "__main__":
    main()
