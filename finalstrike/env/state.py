"""Persist running environment process state for teardown."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

ENV_STATE_REL_PATH = Path(".finalstrike") / "env-state.json"


class ManagedProcess(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    pid: int
    command: str
    pgid: int | None = None

    @property
    def process_group(self) -> int:
        """Process group recorded at start; falls back to pid for legacy state."""
        return self.pgid if self.pgid is not None else self.pid


class EnvState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repo: str
    processes: list[ManagedProcess] = Field(default_factory=list)


def env_state_path(repo: Path) -> Path:
    return repo.resolve() / ENV_STATE_REL_PATH


def load_env_state(repo: Path) -> EnvState | None:
    path = env_state_path(repo)
    if not path.is_file():
        return None
    with path.open(encoding="utf-8") as f:
        raw = json.load(f)
    return EnvState.model_validate(raw)


def save_env_state(repo: Path, state: EnvState) -> Path:
    path = env_state_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(state.model_dump(mode="json"), f, indent=2)
    return path


def clear_env_state(repo: Path) -> None:
    path = env_state_path(repo)
    if path.is_file():
        path.unlink()
