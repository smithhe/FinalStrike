"""Terminal test command runner."""

from __future__ import annotations

import time
from pathlib import Path

from finalstrike.config.models import (
    CommandConfig,
    LayerStatus,
    TerminalCommandResult,
    TerminalLayerResult,
)
from finalstrike.runners.command import CommandRunResult, run_command
from finalstrike.runners.pytest_parser import parse_pytest_output


def run_terminal_layer(
    commands: list[CommandConfig],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout: float | None = 600.0,
    max_retries: int = 0,
    retry_delay: float = 1.0,
) -> TerminalLayerResult:
    """Execute configured test commands and parse pytest output."""
    results: list[TerminalCommandResult] = []
    layer_status = LayerStatus.PASSED
    total_passed = 0
    total_failed = 0

    for command in commands:
        run_result = _run_with_retries(
            command.run,
            cwd=cwd,
            env=env,
            timeout=timeout,
            max_retries=max_retries,
            retry_delay=retry_delay,
        )
        summary = parse_pytest_output(
            f"{run_result.stdout}\n{run_result.stderr}"
        )
        cmd_status = (
            LayerStatus.PASSED if run_result.exit_code == 0 else LayerStatus.FAILED
        )
        if cmd_status == LayerStatus.FAILED:
            layer_status = LayerStatus.FAILED

        total_passed += summary.total_passed
        total_failed += summary.total_failed + summary.total_errors

        results.append(
            TerminalCommandResult(
                name=command.name,
                status=cmd_status,
                exit_code=run_result.exit_code,
                duration_ms=run_result.duration_ms,
                total_passed=summary.total_passed,
                total_failed=summary.total_failed + summary.total_errors,
                stdout=run_result.stdout,
                stderr=run_result.stderr,
            )
        )

    if not commands:
        return TerminalLayerResult(
            status=LayerStatus.SKIPPED,
            commands=[],
            total_passed=0,
            total_failed=0,
        )

    return TerminalLayerResult(
        status=layer_status,
        commands=results,
        total_passed=total_passed,
        total_failed=total_failed,
    )


def _run_with_retries(
    command: str,
    *,
    cwd: Path,
    env: dict[str, str],
    timeout: float | None,
    max_retries: int,
    retry_delay: float,
) -> CommandRunResult:
    last_result: CommandRunResult | None = None
    for attempt in range(max_retries + 1):
        last_result = run_command(command, cwd=cwd, env=env, timeout=timeout)
        if last_result.exit_code == 0 or attempt >= max_retries:
            return last_result
        time.sleep(retry_delay)
    assert last_result is not None
    return last_result
