"""Load acceptance criteria markdown from file or stdin."""

from __future__ import annotations

import sys
from pathlib import Path

from pydantic import BaseModel, ConfigDict


class AcceptanceCriteria(BaseModel):
    """Acceptance criteria markdown passed at runtime."""

    model_config = ConfigDict(extra="forbid")

    content: str
    source: str


def _validate_acceptance_content(content: str, source: str) -> AcceptanceCriteria:
    if not content.strip():
        raise ValueError(f"Acceptance criteria is empty (source: {source})")
    return AcceptanceCriteria(content=content, source=source)


def load_acceptance(path: Path) -> AcceptanceCriteria:
    """Load acceptance criteria from a markdown file."""
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Acceptance criteria file not found: {path}")
    content = path.read_text(encoding="utf-8")
    return _validate_acceptance_content(content, str(path))


def load_acceptance_from_stdin() -> AcceptanceCriteria:
    """Load acceptance criteria from stdin (e.g. piped PR body)."""
    content = sys.stdin.read()
    return _validate_acceptance_content(content, "stdin")
