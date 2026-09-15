"""Tests for target (environment) selection in med_graph.config."""

import io
import os

import pytest

from med_graph.config import (
    AMBIENT_TARGET,
    DEFAULT_TARGET,
    Aborted,
    ConfigError,
    EnvFileMissing,
    InvalidTarget,
    SharedFileLeak,
    Target,
    available_targets,
    confirm_destructive,
    env_file_for,
    load_target,
)

NEO4J_VARS = ("NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD")


@pytest.fixture(autouse=True)
def restore_environ():
    """load_target writes straight into os.environ; undo that after each test.

    monkeypatch.delenv(raising=False) records nothing for a variable that was
    absent, so without this a test that loads an env file leaks its values into
    every later test module.
    """
    saved = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(saved)


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
        with pytest.raises(InvalidTarget, match="target name"):
            env_file_for(name, root)

    def test_a_bad_name_is_catchable_as_both_config_error_and_value_error(self, root):
        """Entry points catch ConfigError; callers written against the stdlib
        contract catch ValueError. A bad name must not escape either."""
        for expected in (ConfigError, ValueError):
            with pytest.raises(expected):
                env_file_for("../../etc/passwd", root)


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

    def test_connection_settings_in_the_shared_file_are_rejected(self, clean_env, root):
        """Even with a valid target file present, a stale NEO4J_URI in .env is
        a migration left-over worth failing on rather than quietly overriding."""
        (root / ".env").write_text("NEO4J_URI=bolt://stale:7687\n")
        write_env(root, "aura", "neo4j+s://abc.databases.neo4j.io")
        with pytest.raises(SharedFileLeak, match="NEO4J_URI"):
            load_target("aura", root=root)

    def test_an_empty_placeholder_in_the_shared_file_is_not_a_leak(self, clean_env, root):
        """.env.example ships blank keys; a blank value configures nothing."""
        (root / ".env").write_text("NEO4J_URI=\nOPENFDA_API_KEY=shared-key\n")
        write_env(root, "aura", "neo4j+s://abc.databases.neo4j.io")
        assert load_target("aura", root=root).uri == "neo4j+s://abc.databases.neo4j.io"

    def test_templates_are_not_offered_as_targets(self, clean_env, root):
        """.env.aura.example is a template to copy, not something to connect to."""
        write_env(root, "local", "bolt://localhost:7687")
        (root / ".env.example").write_text("OPENFDA_API_KEY=\n")
        (root / ".env.aura.example").write_text("NEO4J_URI=\n")
        assert available_targets(root) == ["local"]

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


class TestAmbientFallback:
    """Railway ships no env files and injects real environment variables."""

    def test_a_shared_env_uri_does_not_masquerade_as_injected_config(
        self, clean_env, root
    ):
        """A pre-split .env still holding NEO4J_URI must fail loudly.

        Otherwise the deployment fallback fires on values that were merely read
        out of .env one line earlier, and a command that reads as "reload my
        local graph" silently reloads production.
        """
        (root / ".env").write_text("NEO4J_URI=neo4j+s://prod.databases.neo4j.io\n")
        with pytest.raises(SharedFileLeak, match="NEO4J_URI"):
            load_target(root=root)

    def test_env_var_target_still_falls_back_to_injected_variables(
        self, clean_env, monkeypatch, root
    ):
        """MED_GRAPH_ENV=aura is the natural thing to set on Railway; it must
        not demand a file that deployments deliberately do not ship."""
        for name, value in zip(NEO4J_VARS, ("neo4j+s://x.io", "neo4j", "pw")):
            monkeypatch.setenv(name, value)
        monkeypatch.setenv("MED_GRAPH_ENV", "aura")
        target = load_target(root=root)
        assert target.env_file is None
        assert target.uri == "neo4j+s://x.io"

    def test_an_explicit_flag_still_demands_its_file(self, clean_env, monkeypatch, root):
        """--env is a deliberate local choice, so a typo must not silently
        resolve to whatever happens to be exported."""
        monkeypatch.setenv("NEO4J_URI", "neo4j+s://x.io")
        with pytest.raises(EnvFileMissing):
            load_target("aura", root=root)

    def test_the_ambient_target_is_not_named_after_a_file_it_did_not_read(
        self, clean_env, monkeypatch, root
    ):
        """'target local (REMOTE): neo4j+s://...' is a lie; don't print it."""
        for name, value in zip(NEO4J_VARS, ("neo4j+s://x.io", "neo4j", "pw")):
            monkeypatch.setenv(name, value)
        assert load_target(root=root).name == AMBIENT_TARGET

    def test_a_requested_name_survives_the_fallback(self, clean_env, monkeypatch, root):
        for name, value in zip(NEO4J_VARS, ("neo4j+s://x.io", "neo4j", "pw")):
            monkeypatch.setenv(name, value)
        monkeypatch.setenv("MED_GRAPH_ENV", "aura")
        assert load_target(root=root).name == "aura"


class TestCredentialRedaction:
    def test_describe_hides_a_password_embedded_in_the_uri(self):
        """describe() goes to stdout, which Railway persists as logs."""
        target = Target("aura", None, "neo4j+s://neo4j:hunter2@abc.databases.neo4j.io")
        text = target.describe()
        assert "hunter2" not in text
        assert "abc.databases.neo4j.io" in text

    def test_redaction_keeps_the_port(self):
        target = Target("local", None, "bolt://neo4j:pw@example.com:7687")
        assert "example.com:7687" in target.describe()
        assert "pw" not in target.describe()

    @pytest.mark.parametrize("uri", ["bolt://[::1", "not a uri", ""])
    def test_an_unparseable_uri_is_not_echoed_raw(self, uri):
        """Whatever it is, it is not something safe to print; say so instead."""
        assert Target("odd", None, uri).safe_uri == "<unparseable URI>"


class TestTargetIsRemote:
    @pytest.mark.parametrize(
        "uri",
        [
            "bolt://localhost:7687",
            "bolt://127.0.0.1:7687",
            "neo4j://localhost",
            "bolt://[::1]:7687",
            # The whole 127.0.0.0/8 block is loopback, not just .0.1.
            "bolt://127.0.0.2:7687",
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
            # A bind-any address is not a destination; refuse to call it local.
            "bolt://0.0.0.0:7687",
        ],
    )
    def test_everything_else_is_remote(self, uri):
        assert Target("aura", None, uri).is_remote

    @pytest.mark.parametrize("uri", ["not a uri", "bolt://[::1", ""])
    def test_an_unparseable_uri_is_treated_as_remote(self, uri):
        """Fail safe: an unrecognised target must still prompt for confirmation."""
        assert Target("odd", None, uri).is_remote

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

    def test_the_default_stream_is_resolved_at_call_time(self, monkeypatch):
        """Binding sys.stdin at import would miss pytest's capture and any
        wrapper that replaces the stream later."""
        monkeypatch.setattr("sys.stdin", Terminal("aura\n"))
        target = Target("aura", None, "neo4j+s://abc.databases.neo4j.io")
        confirm_destructive(target, "Delete everything")

    def test_assume_yes_skips_the_prompt(self):
        target = Target("aura", None, "neo4j+s://abc.databases.neo4j.io")
        confirm_destructive(target, "Delete everything", assume_yes=True, stdin=None)

    def test_non_interactive_run_refuses_rather_than_hanging(self):
        target = Target("aura", None, "neo4j+s://abc.databases.neo4j.io")
        with pytest.raises(Aborted, match="--yes"):
            confirm_destructive(target, "Delete everything", stdin=None)

    def test_the_refusal_quotes_the_action_verbatim(self):
        """Actions are printed as "<action> on <target>", so they must survive
        into the error unmangled — .lower() turned "DDL" into "ddl"."""
        target = Target("aura", None, "neo4j+s://abc.databases.neo4j.io")
        with pytest.raises(Aborted, match="Apply schema DDL"):
            confirm_destructive(target, "Apply schema DDL", stdin=None)

    def test_end_of_input_aborts(self):
        target = Target("aura", None, "neo4j+s://abc.databases.neo4j.io")
        with pytest.raises(Aborted):
            confirm_destructive(target, "Delete everything", stdin=Terminal(""))

    def test_surrounding_whitespace_is_tolerated(self):
        target = Target("aura", None, "neo4j+s://abc.databases.neo4j.io")
        confirm_destructive(target, "Delete everything", stdin=Terminal("  aura  \n"))

    def test_the_prompt_does_not_echo_credentials(self, capsys):
        target = Target("aura", None, "neo4j+s://neo4j:hunter2@abc.databases.neo4j.io")
        with pytest.raises(Aborted):
            confirm_destructive(target, "Delete everything", stdin=None)
        assert "hunter2" not in capsys.readouterr().out
