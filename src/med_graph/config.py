"""Which Neo4j instance this process talks to.

One env file per target, `.env.<name>` at the repo root:

  * `.env.local` — docker-compose Neo4j on bolt://localhost:7687
  * `.env.aura`  — the hosted Neo4j Aura instance the deployed API reads

A plain `.env` alongside them holds settings that are the same everywhere, such
as OPENFDA_API_KEY; the target file is applied after it and wins on conflicts.

The target is chosen by an explicit argument, else the MED_GRAPH_ENV variable,
else DEFAULT_TARGET — so forgetting to choose points at the local database
rather than at production.

Deployments (Railway) ship no env files and inject real environment variables
instead; `load_target` falls back to those when no file is present.
"""

from __future__ import annotations

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

TARGET_ENV_VAR = "MED_GRAPH_ENV"

SHARED_ENV_FILE = ".env"

# Target names become a filename suffix, so they stay bare words.
TARGET_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")

LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0"})

REPO_ROOT = Path(__file__).resolve().parents[2]


class EnvFileMissing(Exception):
    """Raised when the selected target has no usable configuration."""


class Aborted(Exception):
    """Raised when the operator declines a destructive operation."""


@dataclass(frozen=True)
class Target:
    """The Neo4j instance a command is pointed at."""

    name: str
    env_file: Path | None
    uri: str

    @property
    def is_remote(self) -> bool:
        """True for anything that is not a loopback address.

        Unparseable URIs count as remote: the caller uses this to decide
        whether to ask before destroying data, so the safe error is to ask.
        """
        try:
            host = urlsplit(self.uri).hostname
        except ValueError:
            return True
        return host not in LOOPBACK_HOSTS

    def describe(self) -> str:
        scope = "REMOTE" if self.is_remote else "local"
        return f"target {self.name} ({scope}): {self.uri}"


def env_file_for(name: str, root: Path = REPO_ROOT) -> Path:
    """Path of the env file backing a target name."""
    if not TARGET_NAME_PATTERN.match(name or ""):
        raise ValueError(
            f"Invalid target name {name!r}; expected a bare word such as 'local' or 'aura'."
        )
    return Path(root) / f".env.{name}"


def available_targets(root: Path = REPO_ROOT) -> list[str]:
    """Target names that have an env file, for use in error messages."""
    names = (
        path.name.removeprefix(".env.")
        for path in Path(root).glob(".env.*")
        if path.is_file()
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


def load_target(name: str | None = None, root: Path = REPO_ROOT) -> Target:
    """Load the chosen target's settings into os.environ and describe it.

    Resolution order for the name: the argument, then MED_GRAPH_ENV, then
    DEFAULT_TARGET.
    """
    root = Path(root)
    resolved = name or os.environ.get(TARGET_ENV_VAR) or DEFAULT_TARGET
    env_file = env_file_for(resolved, root)

    shared = root / SHARED_ENV_FILE
    if shared.is_file():
        _apply(dotenv_values(shared))

    if env_file.is_file():
        _apply(dotenv_values(env_file))
    elif name or os.environ.get(TARGET_ENV_VAR) or not os.environ.get("NEO4J_URI"):
        # A target was asked for by name, or nothing else supplies a URI.
        raise EnvFileMissing(
            f"No {env_file.name} in {root}. "
            f"Available targets: {', '.join(available_targets(root)) or 'none'}. "
            f"Copy .env.{resolved}.example to {env_file.name} and fill it in."
        )
    else:
        # Deployment: real environment variables, no files on disk.
        env_file = None

    uri = os.environ.get("NEO4J_URI")
    if not uri:
        source = env_file.name if env_file else "the environment"
        raise EnvFileMissing(f"NEO4J_URI is not set by {source}; see .env.example")

    return Target(resolved, env_file, uri)


def confirm_destructive(
    target: Target,
    action: str,
    assume_yes: bool = False,
    stdin: IO[str] | None = sys.stdin,
) -> None:
    """Announce the target and, when it is remote, require typed consent.

    Local targets print where they are pointed and continue: wiping a throwaway
    docker database is part of normal development. Remote targets ask for the
    target name, so a reflexive "y" is not enough to drop production data.
    """
    print(f"{action} on {target.describe()}")
    if not target.is_remote or assume_yes:
        return

    if stdin is None or not stdin.isatty():
        raise Aborted(
            f"Refusing to {action.lower()} on remote target {target.name!r} "
            "without confirmation; re-run interactively or pass --yes."
        )

    print(f"This is not a local database. Type {target.name!r} to continue: ", end="", flush=True)
    if stdin.readline().strip() != target.name:
        raise Aborted("Aborted; nothing was written.")
