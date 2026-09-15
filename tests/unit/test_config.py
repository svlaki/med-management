"""Tests for target (environment) selection in med_graph.config."""

import io
import os

import pytest

from med_graph.config import (
    DEFAULT_TARGET,
    Aborted,
    EnvFileMissing,
    Target,
    confirm_destructive,
    env_file_for,
    load_target,
)

NEO4J_VARS = ("NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD")


@pytest.fixture
def clean_env(monkeypatch):
    for name in (*NEO4J_VARS, "MED_GRAPH_ENV"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def root(tmp_path):
    """A repo root holding no env files until a test writes one."""
    return tmp_path


def write_env(root, name, uri, extra=""):
    path = root / f".env.{name}"
    path.write_text(
        f"NEO4J_URI={uri}\nNEO4J_USER=neo4j\nNEO4J_PASSWORD=secret\n{extra}"
    )
    return path


class TestEnvFileFor:
    def test_names_the_file_for_a_target(self, root):
        assert env_file_for("aura", root) == root / ".env.aura"

    @pytest.mark.parametrize("name", ["", "../etc", "a/b", "prod env", "."])
    def test_rejects_a_name_that_is_not_a_bare_word(self, name, root):
        with pytest.raises(ValueError, match="target name"):
            env_file_for(name, root)


class TestLoadTarget:
    def test_defaults_to_local(self, clean_env, root):
        write_env(root, DEFAULT_TARGET, "bolt://localhost:7687")
        target = load_target(root=root)
        assert target.name == DEFAULT_TARGET
        assert target.uri == "bolt://localhost:7687"

    def test_env_var_selects_the_target(self, clean_env, monkeypatch, root):
        write_env(root, "local", "bolt://localhost:7687")
        write_env(root, "aura", "neo4j+s://abc.databases.neo4j.io")
        monkeypatch.setenv("MED_GRAPH_ENV", "aura")
        assert load_target(root=root).uri == "neo4j+s://abc.databases.neo4j.io"

    def test_explicit_name_beats_the_env_var(self, clean_env, monkeypatch, root):
        write_env(root, "local", "bolt://localhost:7687")
        write_env(root, "aura", "neo4j+s://abc.databases.neo4j.io")
        monkeypatch.setenv("MED_GRAPH_ENV", "aura")
        assert load_target("local", root=root).uri == "bolt://localhost:7687"

    def test_file_overrides_a_stale_exported_variable(self, clean_env, monkeypatch, root):
        """An exported NEO4J_URI must not silently shadow the chosen target."""
        monkeypatch.setenv("NEO4J_URI", "bolt://localhost:7687")
        write_env(root, "aura", "neo4j+s://abc.databases.neo4j.io")
        assert load_target("aura", root=root).uri == "neo4j+s://abc.databases.neo4j.io"

    def test_shared_env_file_supplies_non_target_settings(self, clean_env, monkeypatch, root):
        (root / ".env").write_text("OPENFDA_API_KEY=shared-key\n")
        write_env(root, "local", "bolt://localhost:7687")
        monkeypatch.delenv("OPENFDA_API_KEY", raising=False)
        load_target(root=root)
        assert os.environ["OPENFDA_API_KEY"] == "shared-key"

    def test_target_file_wins_over_the_shared_file(self, clean_env, root):
        (root / ".env").write_text("NEO4J_URI=bolt://stale:7687\n")
        write_env(root, "aura", "neo4j+s://abc.databases.neo4j.io")
        assert load_target("aura", root=root).uri == "neo4j+s://abc.databases.neo4j.io"

    def test_missing_file_names_the_available_targets(self, clean_env, root):
        write_env(root, "local", "bolt://localhost:7687")
        write_env(root, "aura", "neo4j+s://abc.databases.neo4j.io")
        with pytest.raises(EnvFileMissing) as error:
            load_target("staging", root=root)
        message = str(error.value)
        assert ".env.staging" in message
        assert "aura" in message and "local" in message

    def test_falls_back_to_ambient_environment_when_no_file_exists(self, clean_env, monkeypatch, root):
        """Railway injects real environment variables and ships no env files."""
        for name, value in zip(NEO4J_VARS, ("neo4j+s://x.io", "neo4j", "pw")):
            monkeypatch.setenv(name, value)
        target = load_target(root=root)
        assert target.env_file is None
        assert target.uri == "neo4j+s://x.io"

    def test_reports_a_missing_uri_rather_than_returning_a_blank_target(self, clean_env, root):
        (root / ".env.local").write_text("NEO4J_USER=neo4j\n")
        with pytest.raises(EnvFileMissing, match="NEO4J_URI"):
            load_target(root=root)


class TestTargetIsRemote:
    @pytest.mark.parametrize(
        "uri",
        [
            "bolt://localhost:7687",
            "bolt://127.0.0.1:7687",
            "neo4j://localhost",
            "bolt://[::1]:7687",
        ],
    )
    def test_loopback_hosts_are_local(self, uri):
        assert not Target("local", None, uri).is_remote

    @pytest.mark.parametrize(
        "uri",
        [
            "neo4j+s://7a10734b.databases.neo4j.io",
            "bolt://10.0.0.4:7687",
            "bolt+s://db.internal:7687",
        ],
    )
    def test_everything_else_is_remote(self, uri):
        assert Target("aura", None, uri).is_remote

    def test_an_unparseable_uri_is_treated_as_remote(self):
        """Fail safe: an unrecognised target must still prompt for confirmation."""
        assert Target("odd", None, "not a uri").is_remote

    def test_description_shows_the_target_and_uri(self):
        text = Target("aura", None, "neo4j+s://abc.databases.neo4j.io").describe()
        assert "aura" in text and "neo4j+s://abc.databases.neo4j.io" in text


class Terminal(io.StringIO):
    """A StringIO that claims to be a tty, standing in for interactive input."""

    def isatty(self) -> bool:
        return True


class TestConfirmDestructive:
    def test_local_target_needs_no_confirmation(self, capsys):
        target = Target("local", None, "bolt://localhost:7687")
        confirm_destructive(target, "Delete everything", stdin=None)
        assert "bolt://localhost:7687" in capsys.readouterr().out

    def test_remote_target_proceeds_when_the_name_is_typed(self):
        target = Target("aura", None, "neo4j+s://abc.databases.neo4j.io")
        confirm_destructive(target, "Delete everything", stdin=Terminal("aura\n"))

    def test_remote_target_aborts_on_anything_else(self):
        target = Target("aura", None, "neo4j+s://abc.databases.neo4j.io")
        with pytest.raises(Aborted):
            confirm_destructive(target, "Delete everything", stdin=Terminal("yes\n"))

    def test_a_piped_stream_is_not_treated_as_consent(self):
        """Redirected stdin must not slip a destructive run past the prompt."""
        target = Target("aura", None, "neo4j+s://abc.databases.neo4j.io")
        with pytest.raises(Aborted, match="--yes"):
            confirm_destructive(target, "Delete everything", stdin=io.StringIO("aura\n"))

    def test_assume_yes_skips_the_prompt(self):
        target = Target("aura", None, "neo4j+s://abc.databases.neo4j.io")
        confirm_destructive(target, "Delete everything", assume_yes=True, stdin=None)

    def test_non_interactive_run_refuses_rather_than_hanging(self):
        target = Target("aura", None, "neo4j+s://abc.databases.neo4j.io")
        with pytest.raises(Aborted, match="--yes"):
            confirm_destructive(target, "Delete everything", stdin=None)
