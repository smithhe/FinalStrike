"""P10 full orchestrator integration tests."""

from __future__ import annotations

import json
import socket
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread
from unittest.mock import patch

import pytest
import yaml
from typer.testing import CliRunner

from finalstrike.cli.main import app
from finalstrike.config.context import load_repo_context
from finalstrike.config.models import (
    LayerStatus,
    UILayerResult,
    UIScenarioResult,
    VerificationPlan,
)
from finalstrike.orchestrator.run import (
    DEFAULT_LAYERS,
    execute_run,
    format_run_summary,
    parse_layers,
    resolve_plan,
)
from tests.conftest import ACCEPTANCE_FILE, FIXTURE_REPO, SMOKE_PLAN_FILE
from tests.support.cassette_repo import (
    CASSETTE_ACCEPTANCE_SMOKE,
    CASSETTE_SMOKE_REPO,
    load_cassette_smoke_context,
)
from tests.support.llm_cassette import ReplayCassetteProvider, load_planner_cassette

runner = CliRunner()
SMOKE_CASSETTE_ID = "smoke-v1"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class _EchoHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"ok")
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        return


@pytest.fixture
def echo_server() -> str:
    port = _free_port()
    server = HTTPServer(("127.0.0.1", port), _EchoHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        thread.join(timeout=2)


@pytest.fixture
def smoke_repo_context():
    return load_cassette_smoke_context(inject_secrets=False)


@pytest.fixture
def smoke_planner_cassette():
    return load_planner_cassette(SMOKE_CASSETTE_ID)


def test_parse_layers_default_is_all() -> None:
    assert parse_layers(None) == list(DEFAULT_LAYERS)


def test_parse_layers_includes_ui() -> None:
    assert "ui" in parse_layers("env,ui")


@pytest.mark.llm_cassette
def test_resolve_plan_from_cassette(
    smoke_repo_context,
    smoke_planner_cassette,
) -> None:
    provider = ReplayCassetteProvider(smoke_planner_cassette.responses)
    plan = resolve_plan(smoke_repo_context, None, planner_provider=provider)
    canonical = VerificationPlan.model_validate(smoke_planner_cassette.canonical_plan)
    assert plan == canonical
    assert provider.calls == 1


@pytest.mark.llm_cassette
def test_execute_run_api_layer_with_cassette_plan(
    smoke_repo_context,
    smoke_planner_cassette,
    echo_server: str,
    tmp_path: Path,
) -> None:
    provider = ReplayCassetteProvider(smoke_planner_cassette.responses)
    config = smoke_repo_context.config.model_copy(
        update={
            "api": smoke_repo_context.config.api.model_copy(
                update={"base_url": echo_server, "health": []}
            )
            if smoke_repo_context.config.api
            else None,
            "evidence": smoke_repo_context.config.evidence.model_copy(update={"video": False}),
        }
    )
    context = smoke_repo_context.model_copy(
        update={
            "repo": tmp_path,
            "config": config,
        }
    )
    (tmp_path / "finalstrike.yaml").write_text(
        yaml.safe_dump(config.model_dump(mode="json")),
        encoding="utf-8",
    )

    result = execute_run(
        context,
        layers=["api"],
        planner_provider=provider,
        render_html=True,
    )
    assert result.layers.api is not None
    assert result.layers.api.status == LayerStatus.PASSED
    assert result.artifacts.html_report == "report.html"
    assert (context.repo / context.config.evidence.output_dir / result.run_id / "report.html").is_file()


@pytest.mark.llm_cassette
def test_execute_run_fail_fast_stops_after_build_failure(tmp_path: Path) -> None:
    config = {
        "version": "1",
        "project": {"name": "fail-fast"},
        "llm": {
            "provider": "openai_compat",
            "base_url": "http://localhost",
            "model": "m",
        },
        "build": {
            "commands": [{"name": "fail", "run": "exit 1"}],
        },
        "tests": {
            "commands": [{"name": "unit", "run": "echo '1 passed in 0.01s'"}],
        },
        "evidence": {"video": False},
        "policy": {"fail_fast": True},
    }
    (tmp_path / "finalstrike.yaml").write_text(
        yaml.safe_dump(config), encoding="utf-8"
    )
    acceptance = tmp_path / "acceptance-smoke.md"
    acceptance.write_text("## AC\n- build fails\n", encoding="utf-8")
    cassette = load_planner_cassette(SMOKE_CASSETTE_ID)
    provider = ReplayCassetteProvider(cassette.responses)
    context = load_repo_context(tmp_path, acceptance_path=acceptance)

    passed_ui = UILayerResult(
        status=LayerStatus.PASSED,
        scenarios=[UIScenarioResult(id="ac-2", status=LayerStatus.PASSED, steps_completed=1)],
    )
    with patch("finalstrike.orchestrator.run.run_ui_layer", return_value=passed_ui):
        result = execute_run(
            context,
            layers=["build", "terminal", "ui"],
            planner_provider=provider,
            render_html=False,
        )

    assert result.layers.build is not None
    assert result.layers.build.status == LayerStatus.FAILED
    assert result.layers.terminal is None
    assert result.layers.ui is None
    assert result.status.value == "failed"


@pytest.mark.llm_cassette
def test_execute_run_no_fail_fast_runs_all_layers(tmp_path: Path) -> None:
    config = {
        "version": "1",
        "project": {"name": "continue"},
        "llm": {
            "provider": "openai_compat",
            "base_url": "http://localhost",
            "model": "m",
        },
        "build": {
            "commands": [{"name": "fail", "run": "exit 1"}],
        },
        "tests": {
            "commands": [{"name": "unit", "run": "echo '1 passed in 0.01s'"}],
        },
        "evidence": {"video": False},
        "policy": {"fail_fast": False},
    }
    (tmp_path / "finalstrike.yaml").write_text(
        yaml.safe_dump(config), encoding="utf-8"
    )
    acceptance = tmp_path / "acceptance-smoke.md"
    acceptance.write_text("## AC\n- mixed results\n", encoding="utf-8")
    cassette = load_planner_cassette(SMOKE_CASSETTE_ID)
    provider = ReplayCassetteProvider(cassette.responses)
    context = load_repo_context(tmp_path, acceptance_path=acceptance)

    passed_ui = UILayerResult(
        status=LayerStatus.PASSED,
        scenarios=[UIScenarioResult(id="ac-2", status=LayerStatus.PASSED, steps_completed=1)],
    )
    with patch("finalstrike.orchestrator.run.run_ui_layer", return_value=passed_ui):
        result = execute_run(
            context,
            layers=["build", "terminal", "ui"],
            fail_fast=False,
            planner_provider=provider,
            render_html=False,
        )

    assert result.layers.build is not None
    assert result.layers.build.status == LayerStatus.FAILED
    assert result.layers.terminal is not None
    assert result.layers.terminal.status == LayerStatus.PASSED
    assert result.layers.ui is not None
    assert result.layers.ui.status == LayerStatus.PASSED
    assert result.status.value == "failed"


@pytest.mark.llm_cassette
def test_run_cli_plan_only(smoke_planner_cassette) -> None:
    result = runner.invoke(
        app,
        [
            "run",
            "--repo",
            str(CASSETTE_SMOKE_REPO),
            "--acceptance",
            str(CASSETTE_ACCEPTANCE_SMOKE),
            "--plan-only",
            "--plan",
            str(smoke_planner_cassette.root / "plan.canonical.json"),
        ],
    )
    assert result.exit_code == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["scenarios"]


@pytest.mark.llm_cassette
def test_run_cli_plan_only_generates_plan(
    smoke_planner_cassette,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from finalstrike.orchestrator import run as orchestrator_run

    provider = ReplayCassetteProvider(smoke_planner_cassette.responses)
    cassette_plan = VerificationPlan.model_validate(smoke_planner_cassette.canonical_plan)

    def _fake_generate(context, provider=None):  # type: ignore[no-untyped-def]
        del context, provider
        return cassette_plan

    monkeypatch.setattr(orchestrator_run, "generate_verification_plan", _fake_generate)
    result = runner.invoke(
        app,
        [
            "run",
            "--repo",
            str(CASSETTE_SMOKE_REPO),
            "--acceptance",
            str(CASSETTE_ACCEPTANCE_SMOKE),
            "--plan-only",
        ],
    )
    assert result.exit_code == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["scenarios"]


def test_run_cli_skip_env_build_terminal() -> None:
    result = runner.invoke(
        app,
        [
            "run",
            "--repo",
            str(FIXTURE_REPO),
            "--acceptance",
            str(ACCEPTANCE_FILE),
            "--plan",
            str(SMOKE_PLAN_FILE),
            "--layers",
            "build,terminal",
            "--skip-env",
        ],
    )
    assert result.exit_code == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "passed"
    assert payload["artifacts"]["html_report"] == "report.html"
    assert "gap(s)" not in result.stderr or "0 gap" in result.stderr.lower() or "Run passed" in result.stderr


def test_format_run_summary_includes_gaps() -> None:
    from finalstrike.config.models import PlanGap, RunResult, RunStatus

    result = RunResult(
        run_id="2026-06-20T14-30-00Z",
        repo="/tmp/repo",
        status=RunStatus.PASSED,
        gaps=[PlanGap(item="OAuth", reason="not configured")],
    )
    summary = format_run_summary(result, artifact_dir=Path("/tmp/repo/.finalstrike/runs/x"))
    assert "1 gap(s)" in summary
    assert "passed" in summary


@pytest.mark.llm_cassette
def test_run_cli_exit_code_failed_api_layer(tmp_path: Path) -> None:
    config = {
        "version": "1",
        "project": {"name": "api-down"},
        "llm": {
            "provider": "openai_compat",
            "base_url": "http://localhost",
            "model": "m",
        },
        "api": {
            "base_url": "http://127.0.0.1:1",
            "health": [{"method": "GET", "path": "/health", "expect_status": 200}],
        },
        "evidence": {"video": False},
    }
    (tmp_path / "finalstrike.yaml").write_text(
        yaml.safe_dump(config), encoding="utf-8"
    )
    acceptance = tmp_path / "acceptance-smoke.md"
    acceptance.write_text("## AC\n- api down\n", encoding="utf-8")
    cassette = load_planner_cassette(SMOKE_CASSETTE_ID)
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(
        json.dumps(cassette.canonical_plan, indent=2),
        encoding="utf-8",
    )
    result = runner.invoke(
        app,
        [
            "run",
            "--repo",
            str(tmp_path),
            "--acceptance",
            str(acceptance),
            "--layers",
            "api",
            "--plan",
            str(plan_path),
        ],
    )
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["layers"]["api"]["status"] == "failed"
