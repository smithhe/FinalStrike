"""P6 computer-use integration tests (GUI VM + platform tools)."""

from __future__ import annotations

import socket
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import urlparse

import pytest

from finalstrike.computer_use.loop import ActionLoop, ReplayActionProvider
from finalstrike.config.models import LayerStatus
from tests.conftest import FIXTURE_REPO
from tests.support.cassette_repo import load_cassette_smoke_context
from tests.support.action_cassette import (
    DEFAULT_SMOKE_TITLE_CASSETTE_ID,
    assert_action_cassette_current,
    load_action_cassette,
)
from tests.test_p6_computer_use import _FakeBrowserProcess, _FakeInput, _FakeScreenshotDriver


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def static_frontend_server(tmp_path: Path) -> str:
    del tmp_path
    static_dir = FIXTURE_REPO / "static"
    port = _free_port()

    class _Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(static_dir), **kwargs)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}/"
    finally:
        server.shutdown()
        thread.join(timeout=2)


@pytest.mark.requires_platform_tools
def test_smoke_title_scenario_with_action_cassette(
    static_frontend_server: str,
    tmp_path: Path,
) -> None:
    cassette = load_action_cassette(DEFAULT_SMOKE_TITLE_CASSETTE_ID)
    assert_action_cassette_current(cassette)

    responses = [
        raw.replace("http://localhost:3000/", static_frontend_server)
        for raw in cassette.responses
    ]

    context = load_cassette_smoke_context(inject_secrets=False)
    assert context.config.ui is not None

    parsed = urlparse(static_frontend_server)
    ephemeral_ui_base = f"{parsed.scheme}://{parsed.netloc}"

    instruction = (
        f'Open {static_frontend_server} and verify the page title is "Sample App"'
    )
    output_root = tmp_path / "runs" / "integration-run"
    loop = ActionLoop(
        instruction=instruction,
        output_dir=output_root,
        provider=ReplayActionProvider(responses),
        browser=context.config.ui.browser,
        max_steps=context.config.policy.max_ui_steps,
        max_action_retries=0,
        max_parse_retries=0,
        screenshot_driver=_FakeScreenshotDriver(),
        input_driver=_FakeInput(),
        ui_base_url=ephemeral_ui_base,
        smoke_route=context.config.ui.smoke_route,
    )

    import finalstrike.computer_use.loop as loop_module

    launched: list[str] = []

    def _fake_launch(url: str, *, browser):  # type: ignore[no-untyped-def]
        del browser
        launched.append(url)
        return _FakeBrowserProcess()

    original = loop_module.launch_browser
    loop_module.launch_browser = _fake_launch
    try:
        loop_result = loop.run()
    finally:
        loop_module.launch_browser = original

    assert loop_result.status == LayerStatus.PASSED
    assert launched == [static_frontend_server]
    assert len(loop_result.steps) == 3
    assert (output_root / "screenshots" / "step-000.png").is_file()
