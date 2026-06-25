"""Tests for P3 command runners and run orchestration."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from finalstrike.cli.main import app
from finalstrike.config.models import CommandConfig, LayerStatus
from finalstrike.orchestrator.run import parse_layers
from finalstrike.runners.build import run_build_layer
from finalstrike.runners.pytest_parser import parse_pytest_output
from finalstrike.runners.terminal import run_terminal_layer

from tests.conftest import ACCEPTANCE_FILE, FIXTURE_REPO
runner = CliRunner()


def test_parse_pytest_output_passed() -> None:
    summary = parse_pytest_output("....\n3 passed in 0.12s\n")
    assert summary.total_passed == 3
    assert summary.total_failed == 0
    assert summary.success is True


def test_parse_pytest_output_failed() -> None:
    summary = parse_pytest_output("1 failed, 2 passed in 0.20s\n")
    assert summary.total_passed == 2
    assert summary.total_failed == 1
    assert summary.success is False


def test_parse_layers_defaults() -> None:
    assert parse_layers(None) == ["env", "build", "terminal"]


def test_parse_layers_unknown() -> None:
    with pytest.raises(ValueError, match="Unknown layer"):
        parse_layers("env,bogus")


def test_parse_layers_includes_api() -> None:
    assert parse_layers("env,api") == ["env", "api"]


def test_run_build_layer_success(tmp_path: Path) -> None:
    commands = [
        CommandConfig(name="ok", run="echo build-ok"),
        CommandConfig(name="optional-fail", run="exit 1", optional=True),
    ]
    result = run_build_layer(commands, cwd=tmp_path, env={})
    assert result.status == LayerStatus.PASSED
    assert result.commands[0].exit_code == 0
    assert result.commands[1].status == LayerStatus.FAILED


def test_run_build_layer_required_failure(tmp_path: Path) -> None:
    commands = [CommandConfig(name="fail", run="exit 2")]
    result = run_build_layer(commands, cwd=tmp_path, env={})
    assert result.status == LayerStatus.FAILED
    assert result.commands[0].exit_code == 2


def test_run_terminal_layer_pytest(tmp_path: Path) -> None:
    test_file = tmp_path / "test_ok.py"
    test_file.write_text(
        "def test_one():\n    assert 1 + 1 == 2\n", encoding="utf-8"
    )
    commands = [CommandConfig(name="unit", run=f"pytest -q {test_file}")]
    result = run_terminal_layer(commands, cwd=tmp_path, env={})
    assert result.status == LayerStatus.PASSED
    assert result.total_passed == 1
    assert result.total_failed == 0


def test_run_terminal_layer_retries(tmp_path: Path) -> None:
    script = tmp_path / "flaky.sh"
    script.write_text(
        "#!/bin/sh\n"
        "count_file=\"flaky.count\"\n"
        "if [ ! -f \"$count_file\" ]; then echo 0 > \"$count_file\"; fi\n"
        "count=$(cat \"$count_file\")\n"
        "count=$((count + 1))\n"
        "echo \"$count\" > \"$count_file\"\n"
        "if [ \"$count\" -lt 2 ]; then exit 1; fi\n"
        "echo '1 passed in 0.01s'\n"
        "exit 0\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    commands = [CommandConfig(name="flaky", run=str(script))]
    result = run_terminal_layer(
        commands, cwd=tmp_path, env={}, max_retries=2, retry_delay=0.01
    )
    assert result.status == LayerStatus.PASSED
    assert result.commands[0].total_passed == 1


def test_run_cli_build_terminal_layers() -> None:
    result = runner.invoke(
        app,
        [
            "run",
            "--repo",
            str(FIXTURE_REPO),
            "--acceptance",
            str(ACCEPTANCE_FILE),
            "--layers",
            "build,terminal",
            "--branch",
            "feature/test",
        ],
    )
    assert result.exit_code == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["branch"] == "feature/test"
    assert payload["status"] == "passed"
    assert payload["layers"]["terminal"]["status"] == "passed"


def test_run_cli_requires_acceptance() -> None:
    result = runner.invoke(
        app,
        ["run", "--repo", str(FIXTURE_REPO), "--layers", "build"],
    )
    assert result.exit_code == 1
    assert "Provide --acceptance" in result.stderr
