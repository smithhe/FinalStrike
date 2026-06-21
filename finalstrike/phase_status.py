"""Registry of implementation phases and stub modules."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PhaseModule:
    """A package path that is scaffolded but not yet implemented."""

    path: str
    phase: int
    summary: str


IMPLEMENTED_PHASES: frozenset[int] = frozenset({0, 1, 2, 3, 4})

STUB_MODULES: tuple[PhaseModule, ...] = (
    PhaseModule("finalstrike/planner/", 5, "LLM test planner"),
    PhaseModule("finalstrike/providers/openai_compat.py", 5, "OpenAI-compatible adapter"),
    PhaseModule("finalstrike/computer_use/", 6, "Computer-use action loop"),
    PhaseModule("finalstrike/computer_use/platform/", 6, "Linux platform drivers"),
    PhaseModule("finalstrike/evidence/", 7, "Evidence recorder and gap analyzer"),
    PhaseModule("finalstrike/reporters/html.py", 8, "HTML report generator"),
    PhaseModule("finalstrike/reporters/slack.py", 9, "Slack bot reporter"),
    PhaseModule("finalstrike/orchestrator/", 10, "Full run state machine"),
)

STUB_TEMPLATES: tuple[PhaseModule, ...] = (
    PhaseModule("templates/report.html.j2", 8, "HTML report Jinja2 template"),
)


def next_unimplemented_phases() -> list[int]:
    """Return phase numbers not yet marked implemented, in order."""
    all_phases = sorted({item.phase for item in (*STUB_MODULES, *STUB_TEMPLATES)})
    return [phase for phase in all_phases if phase not in IMPLEMENTED_PHASES]


def is_stub_source(path: Path, *, project_root: Path) -> PhaseModule | None:
    """Return phase metadata if ``path`` is a known stub file."""
    try:
        relative = path.resolve().relative_to(project_root.resolve())
    except ValueError:
        return None
    relative_posix = relative.as_posix()
    for item in (*STUB_MODULES, *STUB_TEMPLATES):
        if relative_posix == item.path or relative_posix.startswith(f"{item.path}/"):
            return item
    return None
