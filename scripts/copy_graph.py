"""Copy a Neo4j graph from one instance to another, idempotently.

Reads every node and relationship from a source database and MERGEs them into a
target database — typically local docker-compose -> Neo4j Aura. Safe to re-run:
every write is MERGE-based and keyed on the unique constraints the target
already declares, so an interrupted run resumes by simply running it again.

Node keys are not hardcoded. The script reads the source's uniqueness
constraints and uses the constrained property as each label's identity, so a new
label with a constraint is picked up without touching this file.

Relationships are matched on (start key, type, end key). The graph this was
written for has no parallel edges of the same type between the same pair; if the
source does contain them, they collapse to one edge and the verification step at
the end reports the mismatch rather than failing silently.

Run:  .venv/bin/python scripts/copy_graph.py --source-env .env.local.bak --target-env .env
Check only, no writes:  .venv/bin/python scripts/copy_graph.py --dry-run
Compare two graphs:     .venv/bin/python scripts/copy_graph.py --verify-only
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from dotenv import dotenv_values
from neo4j import Driver, GraphDatabase
from neo4j.exceptions import Neo4jError

DEFAULT_BATCH_SIZE = 5_000
IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
UNIQUE_CONSTRAINT_TYPES = ("UNIQUENESS", "NODE_KEY", "NODE_PROPERTY_UNIQUENESS")


class CopyError(Exception):
    """Raised when the copy cannot proceed safely."""


@dataclass(frozen=True)
class NodeSpec:
    """A label and the single property that uniquely identifies its nodes."""

    label: str
    key: str
    count: int


@dataclass(frozen=True)
class RelSpec:
    """A relationship type together with the labels it connects."""

    type: str
    start: NodeSpec
    end: NodeSpec
    count: int


def quote(identifier: str) -> str:
    """Backtick-quote a Cypher identifier, rejecting anything not a bare name.

    Labels, relationship types and property names cannot be passed as query
    parameters, so they are interpolated. Validating them here keeps that
    interpolation from becoming an injection point.
    """
    if not IDENTIFIER_PATTERN.match(identifier):
        raise CopyError(
            f"Refusing to build a query with unsafe identifier {identifier!r}; "
            "expected a plain name such as 'Drug' or 'rxcui'."
        )
    return f"`{identifier}`"


def connect(env_path: str, role: str) -> Driver:
    """Build a verified driver from the NEO4J_* vars in an env file."""
    values = dotenv_values(env_path)
    missing = tuple(
        name
        for name in ("NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD")
        if not values.get(name)
    )
    if missing:
        raise CopyError(
            f"{role} env file {env_path!r} is missing {', '.join(missing)}."
        )
    uri = values["NEO4J_URI"]
    try:
        driver = GraphDatabase.driver(uri, auth=(values["NEO4J_USER"], values["NEO4J_PASSWORD"]))
        driver.verify_connectivity()
    except Exception as error:
        raise CopyError(
            f"Could not connect to the {role} database at {uri}: {error}"
        ) from error
    print(f"  {role:<6} {uri}")
    return driver


def unique_keys(driver: Driver) -> dict[str, str]:
    """Map each constrained label to its unique property, from SHOW CONSTRAINTS."""
    query = (
        "SHOW CONSTRAINTS YIELD type, entityType, labelsOrTypes, properties "
        "RETURN type, entityType, labelsOrTypes, properties"
    )
    with driver.session() as session:
        rows = session.run(query).data()
    return {
        row["labelsOrTypes"][0]: row["properties"][0]
        for row in rows
        if row["entityType"] == "NODE"
        and row["type"] in UNIQUE_CONSTRAINT_TYPES
        and len(row["labelsOrTypes"]) == 1
        and len(row["properties"]) == 1
    }


def node_specs(driver: Driver, keys: dict[str, str]) -> tuple[NodeSpec, ...]:
    """Describe every label present in the source, in copy order."""
    with driver.session() as session:
        multi = session.run(
            "MATCH (n) WHERE size(labels(n)) <> 1 RETURN count(n) AS c"
        ).single()["c"]
        if multi:
            raise CopyError(
                f"{multi} nodes carry zero or multiple labels; this script assumes "
                "exactly one label per node so it can key each node by its constraint."
            )
        counts = session.run(
            "MATCH (n) RETURN labels(n)[0] AS label, count(n) AS count ORDER BY label"
        ).data()

    unconstrained = tuple(row["label"] for row in counts if row["label"] not in keys)
    if unconstrained:
        raise CopyError(
            f"No uniqueness constraint for label(s) {', '.join(unconstrained)}. "
            "Run `med-graph init-schema` against both databases first — without a "
            "unique key the copy cannot be idempotent."
        )
    return tuple(
        NodeSpec(label=row["label"], key=keys[row["label"]], count=row["count"])
        for row in counts
    )


def rel_specs(driver: Driver, nodes: dict[str, NodeSpec]) -> tuple[RelSpec, ...]:
    """Describe every (type, start label, end label) triple present in the source."""
    query = (
        "MATCH (a)-[r]->(b) "
        "RETURN type(r) AS type, labels(a)[0] AS start, labels(b)[0] AS end, "
        "count(*) AS count ORDER BY type, start, end"
    )
    with driver.session() as session:
        rows = session.run(query).data()
    return tuple(
        RelSpec(
            type=row["type"],
            start=nodes[row["start"]],
            end=nodes[row["end"]],
            count=row["count"],
        )
        for row in rows
    )


def read_batches(
    driver: Driver, query: str, total: int, batch_size: int
) -> Iterator[tuple[dict[str, Any], ...]]:
    """Page through a read query with SKIP/LIMIT, yielding immutable batches."""
    for skip in range(0, total, batch_size):
        with driver.session() as session:
            rows = session.run(query, skip=skip, limit=batch_size).data()
        if not rows:
            return
        yield tuple(rows)


def write_batch(driver: Driver, query: str, rows: tuple[dict[str, Any], ...]) -> None:
    """Apply one MERGE batch inside a managed transaction (retries transient errors)."""
    with driver.session() as session:
        session.execute_write(lambda tx: tx.run(query, rows=list(rows)).consume())


def progress(done: int, total: int, what: str, final: bool = False) -> None:
    """Redraw a progress line in place on a terminal; print only the last line to a log."""
    interactive = sys.stdout.isatty()
    if not interactive and not final:
        return
    pct = 100 * done / total if total else 100.0
    line = f"    {what:<46} {done:>7,}/{total:<7,} ({pct:5.1f}%)"
    print(f"\r{line}" if interactive else line, end="" if interactive else "\n", flush=True)


def copy_nodes(
    source: Driver, target: Driver, spec: NodeSpec, batch_size: int
) -> int:
    """MERGE every node of one label into the target, keyed on its constraint."""
    label, key = quote(spec.label), quote(spec.key)
    read = (
        f"MATCH (n:{label}) RETURN properties(n) AS props "
        f"ORDER BY n.{key} SKIP $skip LIMIT $limit"
    )
    write = (
        f"UNWIND $rows AS row "
        f"MERGE (n:{label} {{{key}: row.props.{key}}}) "
        f"SET n += row.props"
    )
    copied = 0
    for batch in read_batches(source, read, spec.count, batch_size):
        write_batch(target, write, batch)
        copied += len(batch)
        progress(copied, spec.count, f"({spec.label})", final=copied >= spec.count)
    if sys.stdout.isatty():
        print()
    return copied


def copy_rels(source: Driver, target: Driver, spec: RelSpec, batch_size: int) -> int:
    """MERGE every relationship of one type, matching endpoints by their keys."""
    rel_type = quote(spec.type)
    start_label, start_key = quote(spec.start.label), quote(spec.start.key)
    end_label, end_key = quote(spec.end.label), quote(spec.end.key)
    read = (
        f"MATCH (a:{start_label})-[r:{rel_type}]->(b:{end_label}) "
        f"RETURN a.{start_key} AS start, b.{end_key} AS end, properties(r) AS props "
        f"ORDER BY start, end SKIP $skip LIMIT $limit"
    )
    write = (
        f"UNWIND $rows AS row "
        f"MATCH (a:{start_label} {{{start_key}: row.start}}) "
        f"MATCH (b:{end_label} {{{end_key}: row.end}}) "
        f"MERGE (a)-[r:{rel_type}]->(b) "
        f"SET r += row.props"
    )
    label = f"({spec.start.label})-[{spec.type}]->({spec.end.label})"
    copied = 0
    for batch in read_batches(source, read, spec.count, batch_size):
        write_batch(target, write, batch)
        copied += len(batch)
        progress(copied, spec.count, label, final=copied >= spec.count)
    if sys.stdout.isatty():
        print()
    return copied


def totals(driver: Driver) -> tuple[dict[str, int], dict[str, int]]:
    """Node counts by label and relationship counts by type."""
    with driver.session() as session:
        nodes = {
            row["label"]: row["count"]
            for row in session.run(
                "MATCH (n) RETURN labels(n)[0] AS label, count(n) AS count"
            ).data()
        }
        rels = {
            row["type"]: row["count"]
            for row in session.run(
                "MATCH ()-[r]->() RETURN type(r) AS type, count(r) AS count"
            ).data()
        }
    return nodes, rels


def verify(source: Driver, target: Driver) -> bool:
    """Compare both graphs label by label and type by type. True if identical."""
    source_nodes, source_rels = totals(source)
    target_nodes, target_rels = totals(target)
    ok = True
    for heading, want, got in (
        ("nodes", source_nodes, target_nodes),
        ("relationships", source_rels, target_rels),
    ):
        print(f"\n  {heading}")
        for name in sorted(want):
            expected, actual = want[name], got.get(name, 0)
            mark = "ok " if expected == actual else "MISMATCH"
            ok = ok and expected == actual
            print(f"    {mark:<9} {name:<20} source={expected:>7,}  target={actual:>7,}")
        for name in sorted(set(got) - set(want)):
            ok = False
            print(f"    EXTRA     {name:<20} source={0:>7,}  target={got[name]:>7,}")
    return ok


def parse_args(argv: tuple[str, ...]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="copy_graph",
        description="Copy a Neo4j graph into another instance, idempotently.",
    )
    parser.add_argument("--source-env", default=".env.local.bak", help="env file for the source database")
    parser.add_argument("--target-env", default=".env", help="env file for the target database")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE, help="rows per transaction")
    parser.add_argument("--dry-run", action="store_true", help="show the plan, write nothing")
    parser.add_argument("--verify-only", action="store_true", help="compare the two graphs, write nothing")
    parser.add_argument(
        "--allow-nonempty",
        action="store_true",
        help="proceed even if the target already holds data (MERGE makes this safe, but confirm you meant it)",
    )
    args = parser.parse_args(list(argv))
    if args.batch_size < 1:
        parser.error("--batch-size must be at least 1")
    if args.source_env == args.target_env:
        parser.error("--source-env and --target-env point at the same file")
    return args


def run(args: argparse.Namespace) -> int:
    print("Connecting")
    source = connect(args.source_env, "source")
    target = connect(args.target_env, "target")
    try:
        if args.verify_only:
            print("\nVerifying")
            return 0 if verify(source, target) else 1

        nodes = node_specs(source, unique_keys(source))
        rels = rel_specs(source, {spec.label: spec for spec in nodes})
        node_total = sum(spec.count for spec in nodes)
        rel_total = sum(spec.count for spec in rels)

        print(f"\nPlan — {node_total:,} nodes, {rel_total:,} relationships")
        for spec in nodes:
            print(f"    {f'({spec.label}) keyed on {spec.key}':<46} {spec.count:>7,}")
        for spec in rels:
            descriptor = f"({spec.start.label})-[{spec.type}]->({spec.end.label})"
            print(f"    {descriptor:<46} {spec.count:>7,}")

        target_nodes, target_rels = totals(target)
        existing = sum(target_nodes.values()) + sum(target_rels.values())
        if existing and not args.allow_nonempty:
            raise CopyError(
                f"Target already holds {sum(target_nodes.values()):,} nodes and "
                f"{sum(target_rels.values()):,} relationships. Re-running is safe "
                "because every write is a MERGE — pass --allow-nonempty to proceed."
            )
        if args.dry_run:
            print("\nDry run — nothing written.")
            return 0

        missing = tuple(spec.label for spec in nodes if spec.label not in unique_keys(target))
        if missing:
            raise CopyError(
                f"Target has no uniqueness constraint for {', '.join(missing)}. "
                "Run `med-graph init-schema` against the target first, or the copy "
                "will duplicate nodes on a re-run."
            )

        print("\nCopying nodes")
        for spec in nodes:
            copy_nodes(source, target, spec, args.batch_size)
        print("\nCopying relationships")
        for spec in rels:
            copy_rels(source, target, spec, args.batch_size)

        print("\nVerifying")
        if not verify(source, target):
            print("\nCounts differ — inspect the mismatches above before trusting the target.")
            return 1
        print("\nDone. Source and target match.")
        return 0
    finally:
        source.close()
        target.close()


def main() -> int:
    try:
        return run(parse_args(tuple(sys.argv[1:])))
    except CopyError as error:
        print(f"\nError: {error}", file=sys.stderr)
        return 1
    except Neo4jError as error:
        print(f"\nNeo4j rejected a query: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted. Re-run to resume — every write is a MERGE.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
