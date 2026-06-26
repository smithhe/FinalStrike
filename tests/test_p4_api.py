"""Tests for P4 API check runner."""

from __future__ import annotations

import json
import socket
import subprocess
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread

import httpx
import pytest
import yaml
from typer.testing import CliRunner

from finalstrike.cli.main import app
from finalstrike.config.context import load_repo_context
from finalstrike.config.models import (
    APIConfig,
    APIExpectation,
    APIPlanStep,
    LayerStatus,
    Scenario,
    ScenarioLayers,
    VerificationPlan,
)
from finalstrike.config.plan import load_verification_plan
from finalstrike.orchestrator.run import execute_run
from finalstrike.runners.api import (
    RESPONSE_BODY_LIMIT,
    build_api_checks,
    extract_json_path,
    run_api_layer,
    sanitize_response_body,
)

from tests.conftest import ACCEPTANCE_FILE, FIXTURE_REPO, SMOKE_PLAN_FILE

runner = CliRunner()


def _wait_for_url(url: str, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with httpx.Client(timeout=1.0) as client:
                response = client.get(url)
                if response.status_code < 500:
                    return
        except httpx.HTTPError:
            pass
        time.sleep(0.1)
    raise RuntimeError(f"service not ready: {url}")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class _EchoHandler(BaseHTTPRequestHandler):
    data = {"id": 42, "name": "widget"}

    def _send(self, code: int, body: bytes, content_type: str = "text/plain") -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("X-App", "fixture")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send(200, b"ok")
            return
        if self.path == "/api/items":
            self._send(200, json.dumps(self.data).encode(), "application/json")
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        if self.path == "/api/items":
            self._send(201, body or b"{}", "application/json")
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


def test_extract_json_path_nested() -> None:
    payload = {"data": {"items": [{"name": "alpha"}]}}
    assert extract_json_path(payload, "data.items.0.name") == "alpha"


def test_sanitize_response_body_redacts_secret_and_truncates() -> None:
    secret = "super-secret-token-value"
    body = secret + ("x" * (RESPONSE_BODY_LIMIT + 100))
    redacted = sanitize_response_body(body, {"API_TOKEN": secret})
    assert secret not in redacted
    assert "truncated at 8192 bytes" in redacted


def test_run_api_layer_skipped_without_config() -> None:
    result = run_api_layer(None, subprocess_env={}, secrets={})
    assert result.status == LayerStatus.SKIPPED
    assert result.checks == []


def test_run_api_layer_health_check(echo_server: str) -> None:
    api_config = APIConfig(
        base_url=echo_server,
        health=[{"method": "GET", "path": "/health", "expect_status": 200}],
    )
    result = run_api_layer(api_config, subprocess_env={}, secrets={})
    assert result.status == LayerStatus.PASSED
    assert len(result.checks) == 1
    check = result.checks[0]
    assert check.actual_status == 200
    assert check.response_body == "ok"


def test_run_api_layer_json_path_and_header_assertions(echo_server: str) -> None:
    api_config = APIConfig(base_url=echo_server, health=[])
    plan = VerificationPlan(
        scenarios=[
            Scenario(
                id="api-1",
                source="items endpoint",
                layers=ScenarioLayers(
                    api=[
                        APIPlanStep(
                            method="GET",
                            path="/api/items",
                            expect=APIExpectation(
                                status=200,
                                json_paths={"id": 42, "name": "widget"},
                                headers={"X-App": "fixture"},
                            ),
                        )
                    ]
                ),
            )
        ]
    )
    result = run_api_layer(
        api_config,
        plan=plan,
        subprocess_env={},
        secrets={},
    )
    assert result.status == LayerStatus.PASSED
    assert result.checks[0].status == LayerStatus.PASSED


def test_run_api_layer_post_from_plan(echo_server: str) -> None:
    api_config = APIConfig(base_url=echo_server, health=[])
    plan = VerificationPlan(
        scenarios=[
            Scenario(
                id="api-post",
                source="create item",
                layers=ScenarioLayers(
                    api=[
                        APIPlanStep(
                            method="POST",
                            path="/api/items",
                            body={"title": "new"},
                            expect=APIExpectation(status=201),
                        )
                    ]
                ),
            )
        ]
    )
    result = run_api_layer(
        api_config,
        plan=plan,
        subprocess_env={},
        secrets={},
    )
    assert result.status == LayerStatus.PASSED
    assert '"title": "new"' in result.checks[0].response_body


def test_run_api_layer_connection_failure() -> None:
    api_config = APIConfig(
        base_url="http://127.0.0.1:1",
        health=[{"method": "GET", "path": "/health", "expect_status": 200}],
    )
    result = run_api_layer(api_config, subprocess_env={}, secrets={})
    assert result.status == LayerStatus.FAILED
    assert result.checks[0].error is not None
    assert "finalstrike env up" in result.checks[0].error
    assert "finalstrike doctor" in result.checks[0].error


def test_build_api_checks_merges_health_and_plan(echo_server: str) -> None:
    api_config = APIConfig(
        base_url=echo_server,
        health=[{"method": "GET", "path": "/health", "expect_status": 200}],
    )
    plan = VerificationPlan(
        scenarios=[
            Scenario(
                id="x",
                source="y",
                layers=ScenarioLayers(
                    api=[
                        APIPlanStep(
                            method="GET",
                            path="/api/items",
                            expect=APIExpectation(status=200),
                        )
                    ]
                ),
            )
        ]
    )
    checks = build_api_checks(api_config, plan)
    assert len(checks) == 2
    assert checks[0].path == "/health"
    assert checks[1].path == "/api/items"


def test_execute_run_api_layer_against_sample_app() -> None:
    port = _free_port()
    proc = subprocess.Popen(
        ["python3", "-m", "sample_app.server", str(port)],
        cwd=FIXTURE_REPO,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    config_path = FIXTURE_REPO / "finalstrike.yaml"
    original = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    patched = dict(original)
    patched["api"] = {
        "base_url": f"http://127.0.0.1:{port}",
        "health": [{"method": "GET", "path": "/health", "expect_status": 200}],
    }
    config_path.write_text(yaml.safe_dump(patched), encoding="utf-8")
    try:
        _wait_for_url(f"http://127.0.0.1:{port}/health")
        context = load_repo_context(FIXTURE_REPO, acceptance_path=ACCEPTANCE_FILE)
        plan = load_verification_plan(SMOKE_PLAN_FILE)
        result = execute_run(context, layers=["api"], plan=plan, render_html=False)
        assert result.layers.api is not None
        assert result.layers.api.status == LayerStatus.PASSED
        assert result.layers.api.checks[0].actual_status == 200
    finally:
        config_path.write_text(yaml.safe_dump(original), encoding="utf-8")
        proc.terminate()
        proc.wait(timeout=5)


def test_run_cli_api_layer_requires_live_service(tmp_path: Path) -> None:
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
    }
    (tmp_path / "finalstrike.yaml").write_text(
        yaml.safe_dump(config), encoding="utf-8"
    )
    acceptance = tmp_path / "acceptance-smoke.md"
    acceptance.write_text("## AC\n- api down\n", encoding="utf-8")
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(SMOKE_PLAN_FILE.read_text(encoding="utf-8"), encoding="utf-8")
    result = runner.invoke(
        app,
        [
            "run",
            "--repo",
            str(tmp_path),
            "--acceptance",
            str(acceptance),
            "--plan",
            str(plan_path),
            "--layers",
            "api",
        ],
    )
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["layers"]["api"]["status"] == "failed"
    assert "finalstrike env up" in payload["layers"]["api"]["checks"][0]["error"]


def test_run_cli_api_layer_with_env(echo_server: str, tmp_path: Path) -> None:
    config = {
        "version": "1",
        "project": {"name": "api-cli"},
        "llm": {
            "provider": "openai_compat",
            "base_url": "http://localhost",
            "model": "m",
        },
        "api": {
            "base_url": echo_server,
            "health": [{"method": "GET", "path": "/health", "expect_status": 200}],
        },
    }
    (tmp_path / "finalstrike.yaml").write_text(
        yaml.safe_dump(config), encoding="utf-8"
    )
    (tmp_path / "acceptance-smoke.md").write_text("## AC\n- ok\n", encoding="utf-8")
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(SMOKE_PLAN_FILE.read_text(encoding="utf-8"), encoding="utf-8")
    result = runner.invoke(
        app,
        [
            "run",
            "--repo",
            str(tmp_path),
            "--acceptance",
            str(tmp_path / "acceptance-smoke.md"),
            "--plan",
            str(plan_path),
            "--layers",
            "api",
        ],
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["layers"]["api"]["status"] == "passed"
