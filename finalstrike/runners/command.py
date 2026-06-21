"""Generic subprocess command runner."""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CommandRunResult:
    """Result of a single shell command execution."""

    exit_code: int
    duration_ms: int
    stdout: str
    stderr: str


def run_command(
    command: str,
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    timeout: float | None = None,
) -> CommandRunResult:
    """Run a shell command in ``cwd`` and capture stdout/stderr."""
    start = time.monotonic()
    run_env = os.environ.copy()
    if env is not None:
        run_env.update(env)
    try:
        completed = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            env=run_env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        exit_code = completed.returncode
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
    except subprocess.TimeoutExpired as exc:
        exit_code = 124
        stdout = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        stderr = (exc.stderr or "") if isinstance(exc.stderr, str) else ""
        stderr = f"{stderr}\nCommand timed out after {timeout}s".strip()
    duration_ms = int((time.monotonic() - start) * 1000)
    return CommandRunResult(
        exit_code=exit_code,
        duration_ms=duration_ms,
        stdout=stdout,
        stderr=stderr,
    )
