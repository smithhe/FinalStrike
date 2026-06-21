"""Load optional AGENTS.md from a target repo."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict

AGENTS_FILENAME = "AGENTS.md"


class AgentsContext(BaseModel):
    """Raw AGENTS.md content for LLM planner injection."""

    model_config = ConfigDict(extra="forbid")

    path: Path | None = None
    content: str = ""
    present: bool = False

    def to_context_block(self) -> str:
        """Return a markdown block suitable for LLM context injection."""
        if not self.present or not self.content.strip():
            return ""
        header = f"## AGENTS.md ({self.path})" if self.path else "## AGENTS.md"
        return f"{header}\n\n{self.content.rstrip()}\n"


def load_agents(repo: Path) -> AgentsContext:
    """Read AGENTS.md from the repo root if present."""
    repo = repo.resolve()
    agents_path = repo / AGENTS_FILENAME
    if not agents_path.is_file():
        return AgentsContext(present=False)

    content = agents_path.read_text(encoding="utf-8")
    return AgentsContext(path=agents_path, content=content, present=True)
