"""Which Neo4j instance this process talks to.

One env file per target, `.env.<name>` at the repo root:

  * `.env.local` — docker-compose Neo4j on bolt://localhost:7687
  * `.env.aura`  — the hosted Neo4j Aura instance the deployed API reads

A plain `.env` alongside them holds settings that are the same everywhere, such
as OPENFDA_API_KEY; the target file is applied after it and wins on conflicts.
Connection details in that shared file are rejected outright — see SharedFileLeak.

The target is chosen by an explicit argument, else the MED_GRAPH_ENV variable,
else DEFAULT_TARGET — so forgetting to choose points at the local database
rather than at production.

Deployments (Railway) ship no env files and inject real environment variables
instead; `load_target` falls back to those and reports the target as
AMBIENT_TARGET rather than claiming to have read a file.
"""

from __future__ import annotations

import ipaddress
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import IO
from urllib.parse import urlsplit

from dotenv import dotenv_values

# Chosen so that an unconfigured run cannot touch production data.
DEFAULT_TARGET = "local"

# Reported when settings come from injected environment variables, not a file.
AMBIENT_TARGET = "ambient"

TARGET_ENV_VAR = "MED_GRAPH_ENV"

SHARED_ENV_FILE = ".env"

# Target names become a filename suffix, so they stay bare words.
TARGET_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")

# Connection settings that must come from a per-target file, never the shared one.
TARGET_ONLY_VARS = ("NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD")

def _detect_repo_root() -> Path | None:
    """The checkout this module was loaded from, or None if installed.

    From source the layout is <root>/src/med_graph/config.py. Installed into
    site-packages it is <site-packages>/med_graph/config.py, where the same
    arithmetic lands on the interpreter's lib directory — a place that has
    nothing to do with this project, and whose contents must never be treated
    as its configuration. Both markers have to line up before a directory is
    accepted as the repo root.
    """
    here = Path(__file__).resolve()
    root = here.parents[2]
    if here.parents[1].name == "src" and (root / "pyproject.toml").is_file():
        return root
    return None


# None when running as an installed package (a wheel, the Railway image):
# there is no source tree, so there are no env files to read.
REPO_ROOT = _detect_repo_root()

# Distinguishes "caller passed nothing" from "caller passed stdin=None", which
# means non-interactive. Resolving sys.stdin at call time keeps a reassigned
# sys.stdin (pytest's capture, a wrapper script) visible.
_USE_SYS_STDIN = object()


class ConfigError(Exception):
    """Base for every configuration problem an entry point should report."""


class EnvFileMissing(ConfigError):
    """Raised when the selected target has no usable configuration."""


class InvalidTarget(ConfigError, ValueError):
    """Raised when a target name could not be turned into a filename."""


class SharedFileLeak(ConfigError):
    """Raised when the shared .env carries per-target connection settings."""


class Aborted(ConfigError):
    """Raised when the operator declines a destructive operation."""


def _hostname(uri: str) -> str | None:
    try:
        return urlsplit(uri).hostname
    except ValueError:
        return None


@dataclass(frozen=True)
class Target:
    """The Neo4j instance a command is pointed at."""

    name: str
    env_file: Path | None
    uri: str

    @property
    def is_remote(self) -> bool:
        """True for anything that is not a loopback address.

        Unparseable URIs count as remote: callers use this to decide whether to
        ask before destroying data, so the safe answer is to ask.
        """
        host = _hostname(self.uri)
        if host is None:
            return True
        if host == "localhost":
            return False
        try:
            # is_loopback covers all of 127.0.0.0/8 and ::1, and correctly
            # rejects 0.0.0.0, which is a bind address rather than a destination.
            return not ipaddress.ip_address(host).is_loopback
        except ValueError:
            return True

    @property
    def safe_uri(self) -> str:
        """The URI with any embedded credentials stripped.

        describe() reaches stdout, which Railway persists as a log stream, so a
        `bolt://user:password@host` URI must not be echoed verbatim.
        """
        try:
            parts = urlsplit(self.uri)
            host = parts.hostname
        except ValueError:
            return "<unparseable URI>"
        if host is None:
            return "<unparseable URI>"
        netloc = f"{host}:{parts.port}" if parts.port else host
        return f"{parts.scheme}://{netloc}" if parts.scheme else netloc

    def describe(self) -> str:
        scope = "REMOTE" if self.is_remote else "local"
        return f"target {self.name} ({scope}): {self.safe_uri}"


def _validate_target_name(name: str) -> str:
    if not TARGET_NAME_PATTERN.match(name or ""):
        raise InvalidTarget(
            f"Invalid target name {name!r}; expected a bare word such as 'local' or 'aura'."
        )
    return name


def env_file_for(name: str, root: Path | None = REPO_ROOT) -> Path:
    """Path of the env file backing a target name."""
    _validate_target_name(name)
    if root is None:
        raise EnvFileMissing(
            f"Cannot look for .env.{name}: no source checkout (running as an "
            "installed package). Configure the database with environment variables."
        )
    return Path(root) / f".env.{name}"


def available_targets(root: Path | None = REPO_ROOT) -> list[str]:
    """Target names that have an env file, for use in error messages.

    Templates (.env.aura.example) and stray backups (.env.local.bak) are
    excluded: the dot in what is left of their name fails the pattern.
    """
    if root is None:
        return []
    names = (
        path.name.removeprefix(".env.")
        for path in Path(root).glob(".env.*")
        if path.is_file() and not path.name.endswith(".example")
    )
    return sorted(name for name in names if TARGET_NAME_PATTERN.match(name))


def _apply(values: dict[str, str | None]) -> None:
    """Push env-file values into os.environ, overriding what is already there.

    dotenv's own default is to keep pre-existing variables, which would let a
    stale exported NEO4J_URI silently shadow the target the caller asked for.
    """
    for key, value in values.items():
        if value is not None:
            os.environ[key] = value


def _load_shared(root: Path) -> None:
    """Apply the shared .env, refusing to let it carry connection settings.

    Before the per-target split, `.env` held NEO4J_* itself. Left in place it
    would look exactly like a deployment's injected variables, so `load_target`
    would report the hosted database under the name `local`. Failing here is
    the difference between a clear error and a wiped production graph.
    """
    shared = root / SHARED_ENV_FILE
    if not shared.is_file():
        return
    values = dotenv_values(shared)
    leaked = [name for name in TARGET_ONLY_VARS if values.get(name)]
    if leaked:
        raise SharedFileLeak(
            f"{shared} sets {', '.join(leaked)}, which belongs in a per-target "
            f"file. Move those lines into .env.local or .env.aura (see "
            f".env.local.example) and leave only shared settings in .env."
        )
    _apply(values)


def load_target(name: str | None = None, root: Path | None = REPO_ROOT) -> Target:
    """Load the chosen target's settings into os.environ and describe it.

    Resolution order for the name: the argument, then MED_GRAPH_ENV, then
    DEFAULT_TARGET. A root of None means there is no source checkout, so the
    file search is skipped and only injected variables are considered.
    """
    requested = name or os.environ.get(TARGET_ENV_VAR)
    resolved = _validate_target_name(requested or DEFAULT_TARGET)

    # Read before any file is applied, so that "already in the environment"
    # cannot be satisfied by a value this function itself just loaded.
    ambient_uri = os.environ.get("NEO4J_URI")

    if root is None:
        if name:
            raise EnvFileMissing(
                f"Cannot read .env.{resolved}: no source checkout (running as an "
                "installed package). Configure the database with environment variables."
            )
        if not ambient_uri:
            raise EnvFileMissing(
                "NEO4J_URI is not set. Running as an installed package, so there "
                "are no env files to fall back on — set it in the environment."
            )
        return Target(requested or AMBIENT_TARGET, None, ambient_uri)

    root = Path(root)
    env_file = env_file_for(resolved, root)
    _load_shared(root)

    if env_file.is_file():
        _apply(dotenv_values(env_file))
    elif ambient_uri:
        # Deployment: real environment variables, no files on disk. An explicit
        # --env is a deliberate local choice, so it still demands its file.
        if name:
            raise EnvFileMissing(_missing_message(env_file, root, resolved))
        env_file = None
        resolved = requested or AMBIENT_TARGET
    else:
        raise EnvFileMissing(_missing_message(env_file, root, resolved))

    uri = os.environ.get("NEO4J_URI")
    if not uri:
        source = env_file.name if env_file else "the environment"
        raise EnvFileMissing(f"NEO4J_URI is not set by {source}; see .env.example")

    return Target(resolved, env_file, uri)


def _missing_message(env_file: Path, root: Path, resolved: str) -> str:
    return (
        f"No {env_file.name} in {root}. "
        f"Available targets: {', '.join(available_targets(root)) or 'none'}. "
        f"Copy .env.{resolved}.example to {env_file.name} and fill it in."
    )


def confirm_destructive(
    target: Target,
    action: str,
    assume_yes: bool = False,
    stdin: IO[str] | None = _USE_SYS_STDIN,
) -> None:
    """Announce the target and, when it is remote, require typed consent.

    Local targets print where they are pointed and continue: wiping a throwaway
    docker database is part of normal development. Remote targets ask for the
    target name, so a reflexive "y" is not enough to drop production data.
    """
    # Flushed so that this always precedes an abort message on stderr.
    print(f"{action} on {target.describe()}", flush=True)
    if not target.is_remote or assume_yes:
        return

    if stdin is _USE_SYS_STDIN:
        stdin = sys.stdin
    if stdin is None or not stdin.isatty():
        raise Aborted(
            f"Refusing to run {action!r} against remote target {target.name!r} "
            "without confirmation; re-run interactively or pass --yes."
        )

    print(f"This is not a local database. Type {target.name!r} to continue: ", end="", flush=True)
    if stdin.readline().strip() != target.name:
        raise Aborted("Aborted; nothing was written.")
