import pytest

from med_graph import cli
from med_graph.graph.client import GraphClient


@pytest.fixture
def clean_env(monkeypatch):
    for name in ("NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD"):
        monkeypatch.delenv(name, raising=False)


def test_missing_config_exits_nonzero(clean_env, monkeypatch, capsys):
    monkeypatch.setattr(cli, "load_dotenv", lambda: None)
    monkeypatch.setattr("sys.argv", ["med-graph", "init-schema"])
    assert cli.main() == 1
    assert "Error" in capsys.readouterr().err


def test_unknown_command_is_rejected(monkeypatch):
    monkeypatch.setattr("sys.argv", ["med-graph", "does-not-exist"])
    with pytest.raises(SystemExit):
        cli.main()


class FakeClient:
    """Stands in for GraphClient so CLI logic is testable without Neo4j."""

    def __init__(self, rows):
        self.rows = rows
        self.queries = []
        self.schema_applied = False

    def execute(self, query, parameters=None):
        self.queries.append(query)
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
    fake_client.rows = [{"label": "Medication", "count": 38}]
    monkeypatch.setattr("sys.argv", ["med-graph", "stats"])
    assert cli.main() == 0
    assert "Medication: 38" in capsys.readouterr().out


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


def test_ingest_loads_condition_with_side_effects(fake_client, monkeypatch, capsys):
    monkeypatch.setattr(cli, "RxClassSource", FakeSource)
    monkeypatch.setattr(cli, "OpenFdaFaersSource", FakeEnricher)
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


def test_profile_by_rxcui_prints_side_effects(fake_client, monkeypatch, capsys):
    fake_client.rows = [
        {
            "side_effect_id": "nausea",
            "name": "Nausea",
            "source": "faers",
            "report_count": 13644,
        }
    ]
    monkeypatch.setattr("sys.argv", ["med-graph", "profile", "--rxcui", "36437"])
    assert cli.main() == 0
    output = capsys.readouterr().out
    assert "Nausea" in output
    assert "13,644" in output


def test_profile_shows_ascii_label_confirmation_marker(fake_client, monkeypatch, capsys):
    fake_client.rows = [
        {
            "side_effect_id": "nausea",
            "name": "Nausea",
            "source": "faers",
            "report_count": 100,
            "label_confirmed": True,
        }
    ]
    monkeypatch.setattr("sys.argv", ["med-graph", "profile", "--rxcui", "36437"])
    assert cli.main() == 0
    output = capsys.readouterr().out
    assert "[label]" in output
    assert "✓" not in output  # no check-mark glyph


def test_profile_confirmed_flag_passes_through(fake_client, monkeypatch, capsys):
    from med_graph.queries.medications import SIDE_EFFECT_PROFILE_CONFIRMED

    fake_client.rows = []
    monkeypatch.setattr(
        "sys.argv", ["med-graph", "profile", "--rxcui", "36437", "--confirmed"]
    )
    assert cli.main() == 0
    assert any(q == SIDE_EFFECT_PROFILE_CONFIRMED for q in fake_client.queries)


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
