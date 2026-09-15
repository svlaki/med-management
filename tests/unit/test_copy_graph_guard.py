"""The copy must not reach a remote database before the operator confirms.

scripts/copy_graph.py defaults to copying the local graph into hosted Aura, so
the ordering between the confirmation and the first write is a safety property,
not a detail. These tests pin that ordering without touching a real database.
"""

import argparse
import importlib.util
import sys
from pathlib import Path

import pytest

from med_graph.config import Aborted, Target

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "copy_graph.py"


@pytest.fixture(scope="module")
def copy_graph():
    spec = importlib.util.spec_from_file_location("copy_graph", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolves NodeSpec.__module__ through sys.modules, so the
    # path-loaded module has to be registered before its classes are usable.
    sys.modules["copy_graph"] = module
    spec.loader.exec_module(module)
    yield module
    del sys.modules["copy_graph"]


class FakeDriver:
    def close(self):
        pass


@pytest.fixture
def traced(copy_graph, monkeypatch):
    """Stub out every database interaction, recording the order of events."""
    events = []
    aura = Target("aura", Path(".env.aura"), "neo4j+s://abc.databases.neo4j.io")
    spec = copy_graph.NodeSpec(label="Drug", key="rxcui", count=1)

    monkeypatch.setattr(copy_graph, "connect", lambda path, role: (FakeDriver(), aura))
    monkeypatch.setattr(copy_graph, "unique_keys", lambda driver: {"Drug": "rxcui"})
    monkeypatch.setattr(copy_graph, "node_specs", lambda driver, keys: [spec])
    monkeypatch.setattr(copy_graph, "rel_specs", lambda driver, by_label: [])
    monkeypatch.setattr(copy_graph, "totals", lambda driver: ({}, {}))
    monkeypatch.setattr(copy_graph, "verify", lambda source, target: True)
    monkeypatch.setattr(
        copy_graph,
        "copy_nodes",
        lambda *a, **k: events.append("write"),
    )
    monkeypatch.setattr(copy_graph, "copy_rels", lambda *a, **k: events.append("write"))

    def confirm(target, action, assume_yes=False, stdin=None):
        events.append(("confirm", target.name, assume_yes))
        if target.is_remote and not assume_yes:
            raise Aborted("declined")

    monkeypatch.setattr(copy_graph, "confirm_destructive", confirm)
    return copy_graph, events


def args(**overrides):
    defaults = dict(
        source_env=".env.local",
        target_env=".env.aura",
        batch_size=10,
        dry_run=False,
        verify_only=False,
        allow_nonempty=True,
        yes=False,
    )
    return argparse.Namespace(**{**defaults, **overrides})


def test_a_declined_confirmation_writes_nothing(traced):
    copy_graph, events = traced
    with pytest.raises(Aborted):
        copy_graph.run(args())
    assert "write" not in events


def test_confirmation_happens_before_the_first_write(traced):
    copy_graph, events = traced
    assert copy_graph.run(args(yes=True)) == 0
    assert events[0][0] == "confirm"
    assert "write" in events


def test_dry_run_neither_prompts_nor_writes(traced):
    """--dry-run is a read-only inspection; it must not demand consent."""
    copy_graph, events = traced
    assert copy_graph.run(args(dry_run=True)) == 0
    assert events == []


def test_verify_only_neither_prompts_nor_writes(traced):
    copy_graph, events = traced
    assert copy_graph.run(args(verify_only=True)) == 0
    assert events == []


def test_the_default_target_is_the_one_confirmed(traced):
    """Guards the specific regression: a bare invocation targets production."""
    copy_graph, events = traced
    parsed = copy_graph.parse_args(())
    assert parsed.target_env == ".env.aura"
    with pytest.raises(Aborted):
        copy_graph.run(args(target_env=parsed.target_env))
    assert events[0] == ("confirm", "aura", False)
