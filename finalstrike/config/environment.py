"""Parse .cursor/environment.json per Cursor format."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

ENVIRONMENT_REL_PATH = Path(".cursor") / "environment.json"


class TerminalConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    command: str


class EnvironmentConfig(BaseModel):
    """Cursor environment.json structure (install, start, terminals)."""

    model_config = ConfigDict(extra="ignore")

    present: bool = False
    path: Path | None = None
    version: str | None = None
    install: str | None = None
    start: str | None = None
    terminals: list[TerminalConfig] = Field(default_factory=list)

    def summary_lines(self) -> list[str]:
        """Human-readable summary for CLI dry-run output."""
        if not self.present:
            return ["(not present)"]
        lines: list[str] = []
        if self.version:
            lines.append(f"version: {self.version}")
        if self.install:
            lines.append(f"install: {self.install}")
        if self.start:
            lines.append(f"start: {self.start}")
        if self.terminals:
            lines.append("terminals:")
            for terminal in self.terminals:
                lines.append(f"  - {terminal.name}: {terminal.command}")
        return lines or ["(empty)"]


def load_environment(repo: Path) -> EnvironmentConfig:
    """Load .cursor/environment.json from a target repo if present."""
    repo = repo.resolve()
    env_path = repo / ENVIRONMENT_REL_PATH
    if not env_path.is_file():
        return EnvironmentConfig(present=False)

    try:
        with env_path.open(encoding="utf-8") as f:
            raw = json.load(f)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{ENVIRONMENT_REL_PATH}: invalid JSON: {exc}") from exc

    if not isinstance(raw, dict):
        raise ValueError(f"{ENVIRONMENT_REL_PATH} must be a JSON object")

    terminals_raw = raw.get("terminals", [])
    terminals: list[TerminalConfig] = []
    if terminals_raw:
        if not isinstance(terminals_raw, list):
            raise ValueError(f"{ENVIRONMENT_REL_PATH}: terminals must be a list")
        for index, entry in enumerate(terminals_raw):
            try:
                terminals.append(TerminalConfig.model_validate(entry))
            except ValidationError as exc:
                raise ValueError(
                    f"{ENVIRONMENT_REL_PATH}: terminals[{index}] invalid: {exc}"
                ) from exc

    install = raw.get("install")
    start = raw.get("start")
    version = raw.get("version")

    return EnvironmentConfig(
        present=True,
        path=env_path,
        version=str(version) if version is not None else None,
        install=str(install) if install is not None else None,
        start=str(start) if start is not None else None,
        terminals=terminals,
    )
