import pytest

from med_graph import cli
from med_graph.config import load_target
from med_graph.graph.client import GraphClient


@pytest.fixture
def clean_env(monkeypatch):
    for name in ("NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD"):
        monkeypatch.delenv(name, raising=False)


def test_missing_config_exits_nonzero(clean_env, monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli, "load_target", lambda name: load_target(name, root=tmp_path))
    monkeypatch.setattr("sys.argv", ["med-graph", "init-schema"])
    assert cli.main() == 1
    assert "Error" in capsys.readouterr().err


def test_unknown_env_target_is_reported(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli, "load_target", lambda name: load_target(name, root=tmp_path))
    monkeypatch.setattr("sys.argv", ["med-graph", "--env", "nope", "init-schema"])
    assert cli.main() == 1
    assert ".env.nope" in capsys.readouterr().err


def test_unknown_command_is_rejected(monkeypatch):
    monkeypatch.setattr("sys.argv", ["med-graph", "does-not-exist"])
    with pytest.raises(SystemExit):
        cli.main()


class FakeClient:
    """Stands in for GraphClient so CLI logic is testable without Neo4j."""

    def __init__(self, rows):
        self.rows = rows
        self.row_sequence: list[list[dict]] = []
        self._call_index = 0
        self.queries = []
        self.schema_applied = False

    def execute(self, query, parameters=None):
        self.queries.append(query)
        if self.row_sequence:
            idx = min(self._call_index, len(self.row_sequence) - 1)
            self._call_index += 1
            return self.row_sequence[idx]
        return self.rows

    def apply_schema(self):
        self.schema_applied = True


@pytest.fixture
def fake_client(monkeypatch):
    from contextlib import contextmanager

    client = FakeClient(rows=[])

    @contextmanager
    def fake_from_env():
        yield client

    monkeypatch.setattr(GraphClient, "from_env", fake_from_env)
    return client


def test_init_schema_applies_schema(fake_client, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["med-graph", "init-schema"])
    assert cli.main() == 0
    assert fake_client.schema_applied
    assert "applied" in capsys.readouterr().out


def test_stats_on_empty_graph(fake_client, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["med-graph", "stats"])
    assert cli.main() == 0
    assert "empty" in capsys.readouterr().out


def test_stats_prints_counts(fake_client, monkeypatch, capsys):
    fake_client.rows = [{"label": "Drug", "count": 306}]
    monkeypatch.setattr("sys.argv", ["med-graph", "stats"])
    assert cli.main() == 0
    assert "Drug: 306" in capsys.readouterr().out


class FakeSource:
    """Stands in for RxClassSource so ingest is testable without the network."""

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return None

    def fetch(self, spec):
        from med_graph.models import EdgeSource, Medication, TreatsEdge
        from med_graph.sources.base import SourceBatch

        return SourceBatch(
            medications=(
                Medication(
                    rxcui="36437", name="sertraline", generic_name="sertraline"
                ),
            ),
            treats=(
                TreatsEdge(
                    medication_rxcui="36437",
                    condition_id=spec.condition.id,
                    source=EdgeSource.RXCLASS,
                ),
            ),
        )


class FakeEnricher:
    """Stands in for OpenFdaFaersSource so ingest is testable without the network."""

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return None

    def enrich(self, medications):
        from med_graph.models import CausesEdge, EdgeSource, SideEffect
        from med_graph.sources.base import SourceBatch

        return SourceBatch(
            side_effects=(SideEffect(id="nausea", name="Nausea"),),
            causes=tuple(
                CausesEdge(
                    medication_rxcui=med.rxcui,
                    side_effect_id="nausea",
                    source=EdgeSource.FAERS,
                    report_count=100,
                )
                for med in medications
            ),
        )


class FakeIndications:
    """Stands in for OpenFdaIndicationSource (no network)."""

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return None

    def approved_rxcuis(self, spec, medications):
        return {med.rxcui for med in medications}


class FakeLabeler:
    """Stands in for OpenFdaLabelSource (no network)."""

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return None

    def confirm(self, medications, batch):
        return batch.model_copy(
            update={
                "causes": tuple(
                    edge.model_copy(update={"label_confirmed": True})
                    for edge in batch.causes
                )
            }
        )


def test_ingest_loads_condition_with_side_effects(fake_client, monkeypatch, capsys):
    monkeypatch.setattr(cli, "RxClassSource", FakeSource)
    monkeypatch.setattr(cli, "OpenFdaFaersSource", FakeEnricher)
    monkeypatch.setattr(cli, "OpenFdaIndicationSource", FakeIndications)
    monkeypatch.setattr(cli, "OpenFdaLabelSource", FakeLabeler)
    monkeypatch.setattr("sys.argv", ["med-graph", "ingest", "--condition", "mdd"])
    assert cli.main() == 0
    output = capsys.readouterr().out
    assert "medications: 1" in output
    assert "side_effects: 1" in output
    assert "causes: 1" in output
    assert any("MERGE (m:Medication" in q for q in fake_client.queries)
    assert any(":CAUSES" in q for q in fake_client.queries)


def test_ingest_rejects_unknown_condition(fake_client, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["med-graph", "ingest", "--condition", "gout"])
    assert cli.main() == 1
    assert "Unknown condition" in capsys.readouterr().err


_DETAIL_ROW = {
    "rxcui": "36437",
    "generic_name": "Sertraline",
    "drug_class": "Antidepressant",
    "has_label": True,
    "product_type": "HUMAN PRESCRIPTION DRUG",
}


def test_profile_by_rxcui_prints_side_effects(fake_client, monkeypatch, capsys):
    fake_client.row_sequence = [
        [_DETAIL_ROW],
        [
            {"side_effect_id": "nausea", "name": "Nausea", "report_count": 13644}
        ],
    ]
    monkeypatch.setattr("sys.argv", ["med-graph", "profile", "--rxcui", "36437"])
    assert cli.main() == 0
    output = capsys.readouterr().out
    assert "Sertraline" in output
    assert "Antidepressant" in output
    assert "Nausea" in output
    assert "13,644" in output


def test_profile_prints_drug_class_and_label_status(fake_client, monkeypatch, capsys):
    fake_client.row_sequence = [[_DETAIL_ROW], []]
    monkeypatch.setattr("sys.argv", ["med-graph", "profile", "--rxcui", "36437"])
    assert cli.main() == 0
    output = capsys.readouterr().out
    assert "Drug Class: Antidepressant" in output
    assert "FDA Label: yes" in output


def test_profile_reports_absent_fda_label(fake_client, monkeypatch, capsys):
    fake_client.row_sequence = [[{**_DETAIL_ROW, "has_label": False}], []]
    monkeypatch.setattr("sys.argv", ["med-graph", "profile", "--rxcui", "36437"])
    assert cli.main() == 0
    assert "FDA Label: no" in capsys.readouterr().out


def test_profile_with_no_side_effects_says_so(fake_client, monkeypatch, capsys):
    fake_client.row_sequence = [[_DETAIL_ROW], []]
    monkeypatch.setattr("sys.argv", ["med-graph", "profile", "--rxcui", "36437"])
    assert cli.main() == 0
    assert "No side effects recorded" in capsys.readouterr().out


def test_profile_rejects_removed_confirmed_flag(fake_client, monkeypatch):
    # HAS_SIDE_EFFECT carries only report_count, so label-confirmed filtering
    # is no longer offered; the flag must not silently no-op.
    monkeypatch.setattr(
        "sys.argv", ["med-graph", "profile", "--rxcui", "36437", "--confirmed"]
    )
    with pytest.raises(SystemExit):
        cli.main()


def test_profile_by_unknown_name_exits_nonzero(fake_client, monkeypatch, capsys):
    fake_client.rows = []  # resolve_rxcui finds nothing
    monkeypatch.setattr("sys.argv", ["med-graph", "profile", "--name", "nope"])
    assert cli.main() == 1
    assert "No medication" in capsys.readouterr().err


def test_profile_requires_rxcui_or_name(fake_client, monkeypatch):
    monkeypatch.setattr("sys.argv", ["med-graph", "profile"])
    with pytest.raises(SystemExit):
        cli.main()


def test_meds_lists_condition_medications(fake_client, monkeypatch, capsys):
    fake_client.rows = [
        {
            "rxcui": "36437",
            "generic_name": "sertraline",
            "drug_class": None,
            "side_effect_count": 12,
        }
    ]
    monkeypatch.setattr("sys.argv", ["med-graph", "meds", "--condition", "mdd"])
    assert cli.main() == 0
    assert "sertraline" in capsys.readouterr().out


def test_avoid_lists_medications(fake_client, monkeypatch, capsys):
    fake_client.rows = [
        {
            "rxcui": "42347",
            "generic_name": "bupropion",
            "drug_class": None,
            "side_effect_count": 5,
        }
    ]
    monkeypatch.setattr(
        "sys.argv",
        ["med-graph", "avoid", "--condition", "mdd", "--side-effect", "weight"],
    )
    assert cli.main() == 0
    assert "bupropion" in capsys.readouterr().out


def test_who_causes_lists_medications(fake_client, monkeypatch, capsys):
    fake_client.rows = [
        {"rxcui": "4493", "generic_name": "fluoxetine", "report_count": 5470}
    ]
    monkeypatch.setattr(
        "sys.argv", ["med-graph", "who-causes", "--side-effect", "insomnia"]
    )
    assert cli.main() == 0
    assert "fluoxetine" in capsys.readouterr().out


def test_export_command_is_gone(fake_client, monkeypatch):
    # The static-snapshot deploy path was retired; the frontend reads the API.
    monkeypatch.setattr("sys.argv", ["med-graph", "export"])
    with pytest.raises(SystemExit):
        cli.main()


class TestRemoteWriteGuard:
    """`med-graph --env aura ingest` writes to production; it must say so and ask."""

    @pytest.fixture
    def aura(self, monkeypatch):
        from pathlib import Path

        from med_graph.config import Target

        target = Target("aura", Path(".env.aura"), "neo4j+s://abc.databases.neo4j.io")
        monkeypatch.setattr(cli, "load_target", lambda name: target)
        return target

    def test_a_write_command_is_confirmed(self, aura, monkeypatch, capsys):
        from med_graph.config import Aborted

        def refuse(target, action, assume_yes=False):
            raise Aborted("declined")

        monkeypatch.setattr(cli, "confirm_destructive", refuse)
        monkeypatch.setattr(
            cli.GraphClient,
            "from_env",
            lambda: pytest.fail("connected despite a declined confirmation"),
        )
        monkeypatch.setattr("sys.argv", ["med-graph", "--env", "aura", "init-schema"])
        assert cli.main() == 1
        assert "Error" in capsys.readouterr().err

    def test_yes_skips_the_prompt(self, aura, monkeypatch):
        seen = {}
        monkeypatch.setattr(
            cli,
            "confirm_destructive",
            lambda target, action, assume_yes=False: seen.update(assume_yes=assume_yes),
        )
        monkeypatch.setattr(cli, "_init_schema", lambda: None)
        monkeypatch.setattr("sys.argv", ["med-graph", "--env", "aura", "--yes", "init-schema"])
        assert cli.main() == 0
        assert seen == {"assume_yes": True}

    def test_a_read_command_announces_the_target_without_asking(
        self, aura, monkeypatch, capsys
    ):
        monkeypatch.setattr(
            cli, "confirm_destructive", lambda *a, **k: pytest.fail("prompted on a read")
        )
        monkeypatch.setattr(cli, "_stats", lambda: None)
        monkeypatch.setattr("sys.argv", ["med-graph", "--env", "aura", "stats"])
        assert cli.main() == 0
        assert "aura" in capsys.readouterr().err
