"""Load secrets vault from .finalstrike/secrets.env."""

from __future__ import annotations

import os
from pathlib import Path


def parse_secrets_content(content: str) -> dict[str, str]:
    """Parse KEY=VALUE lines; skip comments and blank lines."""
    secrets: dict[str, str] = {}
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[len("export ") :].strip()
        if "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        secrets[key] = value
    return secrets


def load_secrets(repo: Path, secrets_file: str) -> tuple[dict[str, str], list[str]]:
    """Load secrets from the path configured in finalstrike.yaml (relative to repo)."""
    repo = repo.resolve()
    secrets_path = repo / secrets_file
    if not secrets_path.is_file():
        return {}, [f"Secrets file not found: {secrets_path.relative_to(repo)}"]

    content = secrets_path.read_text(encoding="utf-8")
    return parse_secrets_content(content), []


def redact_secrets(secrets: dict[str, str]) -> dict[str, str]:
    """Return secrets with values redacted for safe display."""
    return {key: "***" for key in secrets}


def apply_to_environ(
    secrets: dict[str, str],
    base: dict[str, str] | None = None,
) -> dict[str, str]:
    """Merge secrets into an environment mapping for subprocess injection."""
    env = dict(os.environ if base is None else base)
    env.update(secrets)
    return env
