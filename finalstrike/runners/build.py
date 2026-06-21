"""Build and lint command runner."""

from __future__ import annotations

from pathlib import Path

from finalstrike.config.models import (
    BuildCommandResult,
    BuildLayerResult,
    CommandConfig,
    LayerStatus,
)
from finalstrike.runners.command import run_command


def run_build_layer(
    commands: list[CommandConfig],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout: float | None = 600.0,
) -> BuildLayerResult:
    """Execute configured build/lint commands in order."""
    results: list[BuildCommandResult] = []
    layer_status = LayerStatus.PASSED

    for command in commands:
        run_result = run_command(
            command.run,
            cwd=cwd,
            env=env,
            timeout=timeout,
        )
        cmd_status = (
            LayerStatus.PASSED if run_result.exit_code == 0 else LayerStatus.FAILED
        )
        if cmd_status == LayerStatus.FAILED and not command.optional:
            layer_status = LayerStatus.FAILED

        results.append(
            BuildCommandResult(
                name=command.name,
                status=cmd_status,
                exit_code=run_result.exit_code,
                duration_ms=run_result.duration_ms,
                stdout=run_result.stdout,
                stderr=run_result.stderr,
            )
        )

    if not commands:
        return BuildLayerResult(status=LayerStatus.SKIPPED, commands=[])

    return BuildLayerResult(status=layer_status, commands=results)
