import argparse
import sys

from dotenv import load_dotenv

from med_graph.graph.client import GraphClient, GraphConfigError, GraphSchemaError
from med_graph.graph.loader import load_batch
from med_graph.sources.base import SourceFetchError
from med_graph.sources.conditions import CONDITION_REGISTRY
from med_graph.sources.openfda import OpenFdaFaersSource
from med_graph.sources.rxclass import RxClassSource


class UnknownConditionError(Exception):
    """Raised when a condition id is not in the registry."""


def _init_schema() -> None:
    with GraphClient.from_env() as client:
        client.apply_schema()
    print("Schema constraints and indexes applied.")


def _ingest(condition_id: str) -> None:
    spec = CONDITION_REGISTRY.get(condition_id)
    if spec is None:
        known = ", ".join(sorted(CONDITION_REGISTRY))
        raise UnknownConditionError(
            f"Unknown condition '{condition_id}'; known conditions: {known}"
        )
    with RxClassSource() as source:
        batch = source.fetch(spec)
    print(f"fetched {len(batch.medications)} medications; fetching side effects...")
    with OpenFdaFaersSource() as enricher:
        effects = enricher.enrich(batch.medications)
    with GraphClient.from_env() as client:
        client.apply_schema()
        med_counts = load_batch(client, spec.condition, batch)
        effect_counts = load_batch(client, spec.condition, effects)
    totals = {key: med_counts[key] + effect_counts[key] for key in med_counts}
    for record_type, count in totals.items():
        print(f"{record_type}: {count}")


def _stats() -> None:
    with GraphClient.from_env() as client:
        rows = client.execute(
            "MATCH (n) RETURN labels(n)[0] AS label, count(n) AS count ORDER BY label"
        )
    if not rows:
        print("Graph is empty.")
        return
    for row in rows:
        print(f"{row['label']}: {row['count']}")


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(prog="med-graph")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init-schema", help="Create graph constraints and indexes")
    subparsers.add_parser("stats", help="Show node counts by label")
    ingest_parser = subparsers.add_parser(
        "ingest", help="Fetch a condition's medications and load them into the graph"
    )
    ingest_parser.add_argument("--condition", required=True, help="e.g. mdd")

    args = parser.parse_args()
    try:
        if args.command == "ingest":
            _ingest(args.condition)
        else:
            commands = {"init-schema": _init_schema, "stats": _stats}
            commands[args.command]()
    except (
        GraphConfigError,
        GraphSchemaError,
        SourceFetchError,
        UnknownConditionError,
    ) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
