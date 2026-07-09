import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

from med_graph.graph.client import GraphClient, GraphConfigError, GraphSchemaError
from med_graph.graph.loader import load_batch
from med_graph.snapshot import build_snapshot
from med_graph.queries.medications import (
    medications_by_side_effect,
    medications_for_condition,
    medications_without_side_effect,
    resolve_rxcui,
    side_effect_profile,
)
from med_graph.sources.base import SourceFetchError
from med_graph.sources.conditions import CONDITION_REGISTRY
from med_graph.sources.openfda import OpenFdaFaersSource
from med_graph.sources.openfda_label import OpenFdaLabelSource
from med_graph.sources.rxclass import RxClassSource


class UnknownConditionError(Exception):
    """Raised when a condition id is not in the registry."""


class MedicationNotFoundError(Exception):
    """Raised when a medication name cannot be resolved to an rxcui."""


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
    print(f"cross-referencing {len(effects.causes)} side effects against FDA labels...")
    with OpenFdaLabelSource() as labeler:
        effects = labeler.confirm(batch.medications, effects)
    with GraphClient.from_env() as client:
        client.apply_schema()
        med_counts = load_batch(client, spec.condition, batch)
        effect_counts = load_batch(client, spec.condition, effects)
    totals = {key: med_counts[key] + effect_counts[key] for key in med_counts}
    for record_type, count in totals.items():
        print(f"{record_type}: {count}")


def _fmt_count(value: int | None) -> str:
    return f"{value:,}" if value is not None else "-"


def _confirmation_marker(label_confirmed: bool | None) -> str:
    if label_confirmed is True:
        return "[label]"
    if label_confirmed is False:
        return "faers-only"
    return "unchecked"


def _profile(rxcui: str | None, name: str | None, limit: int, confirmed_only: bool) -> None:
    with GraphClient.from_env() as client:
        if rxcui is None:
            rxcui = resolve_rxcui(client, name)
            if rxcui is None:
                raise MedicationNotFoundError(f"No medication named '{name}' in graph")
        reports = side_effect_profile(client, rxcui, limit, confirmed_only)
    if not reports:
        print(f"No side effects recorded for rxcui {rxcui}.")
        return
    for report in reports:
        marker = _confirmation_marker(report.label_confirmed)
        print(f"{_fmt_count(report.report_count):>12}  {marker:<12}  {report.name}")


def _meds(condition_id: str) -> None:
    with GraphClient.from_env() as client:
        meds = medications_for_condition(client, condition_id)
    if not meds:
        print(f"No medications found for condition '{condition_id}'.")
        return
    for med in meds:
        print(f"{med.generic_name}  ({med.side_effect_count} side effects)")


def _avoid(condition_id: str, side_effect: str) -> None:
    with GraphClient.from_env() as client:
        meds = medications_without_side_effect(client, condition_id, side_effect)
    if not meds:
        print(f"No '{condition_id}' medications avoid '{side_effect}'.")
        return
    for med in meds:
        print(f"{med.generic_name}  ({med.side_effect_count} side effects)")


def _who_causes(side_effect_id: str) -> None:
    with GraphClient.from_env() as client:
        causes = medications_by_side_effect(client, side_effect_id)
    if not causes:
        print(f"No medications recorded causing '{side_effect_id}'.")
        return
    for cause in causes:
        print(f"{_fmt_count(cause.report_count):>12}  {cause.generic_name}")


def _export(out_path: str) -> None:
    with GraphClient.from_env() as client:
        snapshot = build_snapshot(client)
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, indent=2))
    med_count = sum(len(g["medications"]) for g in snapshot["graphs"].values())
    print(
        f"Wrote {path} — {len(snapshot['conditions'])} condition(s), "
        f"{med_count} medication(s)."
    )


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

    profile_parser = subparsers.add_parser(
        "profile", help="Show a medication's side-effect profile, most-reported first"
    )
    profile_target = profile_parser.add_mutually_exclusive_group(required=True)
    profile_target.add_argument("--rxcui", help="RxNorm CUI, e.g. 36437")
    profile_target.add_argument("--name", help="Generic name, e.g. sertraline")
    profile_parser.add_argument("--limit", type=int, default=20)
    profile_parser.add_argument(
        "--confirmed",
        action="store_true",
        help="Only show side effects confirmed in the FDA label",
    )

    meds_parser = subparsers.add_parser(
        "meds", help="List medications that treat a condition"
    )
    meds_parser.add_argument("--condition", required=True, help="e.g. mdd")

    avoid_parser = subparsers.add_parser(
        "avoid", help="List a condition's medications not linked to a side effect"
    )
    avoid_parser.add_argument("--condition", required=True, help="e.g. mdd")
    avoid_parser.add_argument("--side-effect", required=True, help="e.g. weight")

    who_parser = subparsers.add_parser(
        "who-causes", help="List medications reported to cause a side effect"
    )
    who_parser.add_argument("--side-effect", required=True, help="e.g. insomnia")

    export_parser = subparsers.add_parser(
        "export", help="Write a static JSON snapshot for the standalone web app"
    )
    export_parser.add_argument(
        "--out",
        default="frontend/public/snapshot.json",
        help="Output path for the snapshot JSON",
    )

    args = parser.parse_args()
    try:
        if args.command == "ingest":
            _ingest(args.condition)
        elif args.command == "profile":
            _profile(args.rxcui, args.name, args.limit, args.confirmed)
        elif args.command == "meds":
            _meds(args.condition)
        elif args.command == "avoid":
            _avoid(args.condition, args.side_effect)
        elif args.command == "who-causes":
            _who_causes(args.side_effect)
        elif args.command == "export":
            _export(args.out)
        else:
            commands = {"init-schema": _init_schema, "stats": _stats}
            commands[args.command]()
    except (
        GraphConfigError,
        GraphSchemaError,
        SourceFetchError,
        UnknownConditionError,
        MedicationNotFoundError,
    ) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
