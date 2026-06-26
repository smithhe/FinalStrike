"""Run artifact directory layout and path helpers."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from finalstrike.config.context import RepoContext
from finalstrike.config.models import RunResult


def new_run_id() -> str:
    """UTC timestamp run identifier shared across layers."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")


class ArtifactStore:
    """Create and manage the canonical run artifact directory."""

    VIDEO_FILENAME = "desktop.mp4"
    RAW_VIDEO_FILENAME = "desktop.webm"
    RESULT_FILENAME = "result.json"

    def __init__(self, context: RepoContext, *, run_id: str | None = None) -> None:
        self.context = context
        self.run_id = run_id or new_run_id()
        self.root = (
            context.repo / context.config.evidence.output_dir / self.run_id
        ).resolve()
        self._screenshots: list[str] = []

    def ensure_dirs(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    @property
    def screenshots_dir(self) -> Path:
        return self.root / "screenshots"

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"

    @property
    def video_path(self) -> Path:
        return self.root / self.VIDEO_FILENAME

    @property
    def raw_video_path(self) -> Path:
        return self.root / self.RAW_VIDEO_FILENAME

    @property
    def result_path(self) -> Path:
        return self.root / self.RESULT_FILENAME

    def relative_to_run(self, path: Path | str) -> str:
        """Return a path relative to the run root for RunResult artifacts."""
        candidate = Path(path)
        if candidate.is_absolute():
            return candidate.resolve().relative_to(self.root).as_posix()
        return candidate.as_posix()

    def register_screenshot(self, relative_path: str) -> str:
        normalized = self.relative_to_run(relative_path)
        if normalized not in self._screenshots:
            self._screenshots.append(normalized)
        return normalized

    @property
    def screenshots(self) -> list[str]:
        return list(self._screenshots)

    def write_log(self, name: str, content: str) -> str:
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        path = self.logs_dir / name
        path.write_text(content, encoding="utf-8")
        return self.relative_to_run(path)

    def write_result(self, result: RunResult) -> Path:
        self.ensure_dirs()
        payload = result.model_dump(mode="json")
        with self.result_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
        return self.result_path
