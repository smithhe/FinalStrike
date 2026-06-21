"""P5 planner integration tests — cassette replay and plan→run pipeline."""

from __future__ import annotations

import json
import socket
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

import pytest

from finalstrike.config.context import load_repo_context
from finalstrike.config.models import APIConfig, LayerStatus, VerificationPlan
from finalstrike.fixture_capabilities import load_capabilities
from finalstrike.planner.planner import generate_verification_plan
from finalstrike.runners.api import run_api_layer
from tests.conftest import ACCEPTANCE_FILE, ACCEPTANCE_SMOKE, FIXTURE_REPO
from tests.support.llm_cassette import (
    ReplayCassetteProvider,
    assert_cassette_matches_context,
    load_planner_cassette,
)
from tests.support.plan_assertions import (
    assert_plan_covers_acceptance,
    assert_plan_covers_capabilities,
    assert_plan_has_layer_coverage,
)

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
    return load_repo_context(
        FIXTURE_REPO,
        acceptance_path=ACCEPTANCE_FILE,
        inject_secrets=False,
    )


@pytest.fixture
def smoke_planner_cassette():
    return load_planner_cassette(SMOKE_CASSETTE_ID)


@pytest.mark.llm_cassette
def test_planner_cassette_meta_is_current(smoke_planner_cassette) -> None:
    cassette = smoke_planner_cassette
    assert cassette.meta.id == SMOKE_CASSETTE_ID
    assert cassette.meta.phase == 5
    assert cassette.meta.component == "planner"


@pytest.mark.llm_cassette
def test_planner_cassette_matches_repo_inputs(
    smoke_repo_context,
    smoke_planner_cassette,
) -> None:
    assert_cassette_matches_context(
        smoke_planner_cassette,
        smoke_repo_context,
        acceptance_path=ACCEPTANCE_SMOKE,
    )


@pytest.mark.llm_cassette
def test_planner_cassette_replay_matches_canonical(
    smoke_repo_context,
    smoke_planner_cassette,
) -> None:
    provider = ReplayCassetteProvider(smoke_planner_cassette.responses)
    plan = generate_verification_plan(smoke_repo_context, provider=provider)
    canonical = VerificationPlan.model_validate(smoke_planner_cassette.canonical_plan)
    assert plan == canonical
    assert provider.calls == 1


@pytest.mark.llm_cassette
def test_planner_cassette_replay_structural_coverage(
    smoke_repo_context,
    smoke_planner_cassette,
) -> None:
    provider = ReplayCassetteProvider(smoke_planner_cassette.responses)
    plan = generate_verification_plan(smoke_repo_context, provider=provider)
    capabilities = load_capabilities(FIXTURE_REPO / "capabilities.yaml")
    acceptance_text = ACCEPTANCE_SMOKE.read_text(encoding="utf-8")

    assert_plan_has_layer_coverage(plan)
    assert_plan_covers_acceptance(plan, acceptance_text)
    assert_plan_covers_capabilities(plan, capabilities)


@pytest.mark.llm_cassette
def test_planner_cassette_drives_api_layer(
    smoke_repo_context,
    smoke_planner_cassette,
    echo_server: str,
) -> None:
    provider = ReplayCassetteProvider(smoke_planner_cassette.responses)
    plan = generate_verification_plan(smoke_repo_context, provider=provider)
    api_config = APIConfig(
        base_url=echo_server,
        health=[],
    )
    result = run_api_layer(
        api_config,
        plan=plan,
        subprocess_env={},
        secrets={},
    )
    assert result.status == LayerStatus.PASSED
    assert result.checks
    assert all(check.actual_status == 200 for check in result.checks)


@pytest.mark.llm_cassette
def test_canonical_plan_json_is_stable(smoke_planner_cassette) -> None:
    """Golden file guard — canonical plan must match committed JSON exactly."""
    on_disk = json.loads(
        (smoke_planner_cassette.root / "plan.canonical.json").read_text(
            encoding="utf-8"
        )
    )
    assert on_disk == smoke_planner_cassette.canonical_plan
