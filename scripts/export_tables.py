"""Dump the datasets we work with into browsable tables (CSV + one Excel workbook).

Reads the populated Neo4j graph and flattens it into tidy DataFrames grouped by
data source, so you can explore the RxClass / openFDA / FAERS data in pandas,
Excel, or anything that opens CSV.

Run:  .venv/bin/python scripts/export_tables.py
Output: data_exports/*.csv  and  data_exports/med_graph_datasets.xlsx

Interactive:
    import pandas as pd
    treats = pd.read_csv("data_exports/rxclass_treats.csv")
    faers  = pd.read_csv("data_exports/faers_side_effects.csv")
"""

from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from med_graph.graph.client import GraphClient

OUT_DIR = Path(__file__).resolve().parent.parent / "data_exports"

# Each entry: (filename, source label, Cypher). Column meaning is documented so
# the tables are self-explanatory when opened cold.
QUERIES: dict[str, tuple[str, str]] = {
    # RxClass: which medications may treat which conditions (the TREATS edges),
    # with the openFDA-derived FDA-approved flag layered on.
    "rxclass_treats": (
        "RxClass (may_treat) + openFDA indications",
        """
        MATCH (m:Medication)-[t:TREATS]->(c:Condition)
        RETURN c.id AS condition_id, c.name AS condition, c.icd10 AS icd10,
               m.rxcui AS rxcui, m.generic_name AS medication,
               t.source AS source, t.fda_approved AS fda_approved
        ORDER BY condition, medication
        """,
    ),
    # FAERS: reported adverse-event side effects per medication, with the raw
    # report volume, plus whether the FDA label confirms it (openFDA label).
    "faers_side_effects": (
        "FAERS reports + openFDA label confirmation",
        """
        MATCH (m:Medication)-[r:CAUSES]->(s:SideEffect)
        RETURN m.rxcui AS rxcui, m.generic_name AS medication,
               s.name AS side_effect, s.meddra_term AS meddra_term,
               r.report_count AS report_count, r.source AS source,
               r.label_confirmed AS label_confirmed
        ORDER BY medication, report_count DESC
        """,
    ),
    # Dimension tables (the nodes themselves).
    "medications": (
        "Medications (RxNorm)",
        """
        MATCH (m:Medication)
        RETURN m.rxcui AS rxcui, m.generic_name AS generic_name,
               m.drug_class AS drug_class
        ORDER BY generic_name
        """,
    ),
    "conditions": (
        "Conditions",
        """
        MATCH (c:Condition)
        RETURN c.id AS id, c.name AS name, c.icd10 AS icd10 ORDER BY name
        """,
    ),
    "side_effects": (
        "Side effects (MedDRA)",
        """
        MATCH (s:SideEffect)
        RETURN s.id AS id, s.name AS name, s.meddra_term AS meddra_term
        ORDER BY name
        """,
    ),
}


def main() -> None:
    load_dotenv()
    OUT_DIR.mkdir(exist_ok=True)
    frames: dict[str, pd.DataFrame] = {}

    with GraphClient.from_env() as client:
        for name, (label, cypher) in QUERIES.items():
            rows = client.execute(cypher)
            df = pd.DataFrame(rows)
            frames[name] = df
            csv_path = OUT_DIR / f"{name}.csv"
            df.to_csv(csv_path, index=False)
            print(f"[{label}]  {name}.csv  ({len(df)} rows, {len(df.columns)} cols)")
            print(df.head(5).to_string(index=False))
            print()

    xlsx_path = OUT_DIR / "med_graph_datasets.xlsx"
    with pd.ExcelWriter(xlsx_path) as writer:
        for name, df in frames.items():
            df.to_excel(writer, sheet_name=name[:31], index=False)
    print(f"Wrote workbook: {xlsx_path}")
    print(f"All files in:   {OUT_DIR}")


if __name__ == "__main__":
    main()
