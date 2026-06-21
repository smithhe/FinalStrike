"""Tests for P2 environment orchestrator."""

from __future__ import annotations

import json
import socket
import subprocess
import time
from pathlib import Path

import httpx
import pytest
import yaml
from typer.testing import CliRunner

from finalstrike.cli.main import app
from finalstrike.config.context import load_repo_context
from finalstrike.config.environment import EnvironmentConfig
from finalstrike.config.models import FinalStrikeConfig, LayerStatus
from finalstrike.env.health import wait_for_health
from finalstrike.env.orchestrator import EnvOrchestrator
from finalstrike.env.state import load_env_state

FIXTURE_REPO = Path(__file__).resolve().parents[1] / "fixtures" / "sample-app"
ACCEPTANCE_FILE = FIXTURE_REPO / "acceptance.md"
runner = CliRunner()


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _write_minimal_env_repo(tmp_path: Path, *, port: int) -> Path:
    config = {
        "version": "1",
        "project": {"name": "env-test"},
        "llm": {
            "provider": "openai_compat",
            "base_url": "http://localhost",
            "model": "m",
        },
        "api": {
            "base_url": f"http://127.0.0.1:{port}",
            "health": [{"method": "GET", "path": "/", "expect_status": 200}],
        },
    }
    (tmp_path / "finalstrike.yaml").write_text(
        yaml.safe_dump(config), encoding="utf-8"
    )
    cursor_dir = tmp_path / ".cursor"
    cursor_dir.mkdir()
    env_json = {
        "install": "echo install-ok",
        "terminals": [
            {
                "name": "api",
                "command": f"python3 -m http.server {port}",
            }
        ],
    }
    (cursor_dir / "environment.json").write_text(
        json.dumps(env_json), encoding="utf-8"
    )
    return tmp_path


def test_wait_for_health_success() -> None:
    port = _free_port()
    proc = subprocess.Popen(
        ["python3", "-m", "http.server", str(port)],
        cwd=FIXTURE_REPO,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        from finalstrike.config.models import HealthCheckConfig

        outcomes = wait_for_health(
            f"http://127.0.0.1:{port}",
            [HealthCheckConfig(path="/")],
            timeout=10.0,
        )
        assert len(outcomes) == 1
        assert outcomes[0].passed is True
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_env_orchestrator_install_and_teardown(tmp_path: Path) -> None:
    port = _free_port()
    repo = _write_minimal_env_repo(tmp_path, port=port)
    context = load_repo_context(repo, acceptance_path=ACCEPTANCE_FILE)
    orchestrator = EnvOrchestrator(
        repo=context.repo,
        environment=context.environment,
        config=context.config,
        subprocess_env=context.subprocess_env,
        health_timeout=15.0,
    )
    try:
        result = orchestrator.up()
        assert result.status == LayerStatus.PASSED
        assert "install-ok" in result.logs or "install" in result.logs
        state = load_env_state(repo)
        assert state is not None
        assert len(state.processes) == 1
    finally:
        orchestrator.down()
        assert load_env_state(repo) is None


def test_env_orchestrator_down_without_state(tmp_path: Path) -> None:
    repo = _write_minimal_env_repo(tmp_path, port=_free_port())
    context = load_repo_context(repo, acceptance_path=ACCEPTANCE_FILE)
    orchestrator = EnvOrchestrator(
        repo=context.repo,
        environment=EnvironmentConfig(present=False),
        config=context.config,
        subprocess_env=context.subprocess_env,
    )
    messages = orchestrator.down()
    assert messages == []


@pytest.mark.integration
def test_env_up_cli_sample_app() -> None:
    """Start fixture services and verify /health responds."""
    result = runner.invoke(
        app,
        ["env", "up", "--repo", str(FIXTURE_REPO), "--health-timeout", "30"],
    )
    try:
        assert result.exit_code == 0, result.stderr
        assert "Environment ready" in result.stderr
        response = httpx.get("http://127.0.0.1:8080/health", timeout=5.0)
        assert response.status_code == 200
    finally:
        down = runner.invoke(app, ["env", "down", "--repo", str(FIXTURE_REPO)])
        assert down.exit_code == 0


def test_env_up_skips_without_environment_json(tmp_path: Path) -> None:
    config = {
        "version": "1",
        "project": {"name": "no-env"},
        "llm": {
            "provider": "openai_compat",
            "base_url": "http://localhost",
            "model": "m",
        },
    }
    (tmp_path / "finalstrike.yaml").write_text(
        yaml.safe_dump(config), encoding="utf-8"
    )
    result = runner.invoke(app, ["env", "up", "--repo", str(tmp_path)])
    assert result.exit_code == 0
    assert "skipped" in result.stderr.lower()
