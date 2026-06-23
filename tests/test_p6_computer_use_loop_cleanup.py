"""Browser cleanup edge-case tests for the action loop."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from finalstrike.computer_use.loop import ActionLoop, ReplayActionProvider
from finalstrike.config.models import BrowserKind, LayerStatus
from tests.test_p6_computer_use import (
    UI_BASE_URL,
    _FakeBrowserProcess,
    _FakeInput,
    _FakeScreenshotDriver,
)


class _StubbornProcess:
    def __init__(self) -> None:
        self.terminated = False
        self.killed = False
        self._alive = True

    def poll(self) -> int | None:
        return None if self._alive else 0

    def terminate(self) -> None:
        self.terminated = True

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        if self.killed:
            raise subprocess.TimeoutExpired(cmd="browser", timeout=2)
        if self.terminated:
            raise subprocess.TimeoutExpired(cmd="browser", timeout=5)
        return 0

    def kill(self) -> None:
        self.killed = True


def test_cleanup_survives_second_wait_timeout(tmp_path: Path) -> None:
    responses = [
        json.dumps(
            {
                "thought": "launch",
                "action": {"type": "launch", "url": "http://localhost:3000/"},
            }
        ),
        json.dumps(
            {
                "thought": "done",
                "action": {"type": "done", "success": True, "message": "ok"},
            }
        ),
    ]

    import finalstrike.computer_use.loop as loop_module

    stubborn = _StubbornProcess()

    def _fake_launch(url: str, *, browser: BrowserKind) -> _StubbornProcess:
        del url, browser
        return stubborn

    loop = ActionLoop(
        instruction="verify",
        output_dir=tmp_path,
        provider=ReplayActionProvider(responses),
        browser=BrowserKind.CHROMIUM,
        max_steps=3,
        max_action_retries=0,
        max_parse_retries=0,
        screenshot_driver=_FakeScreenshotDriver(),
        input_driver=_FakeInput(),
        ui_base_url=UI_BASE_URL,
    )

    original = loop_module.launch_browser
    loop_module.launch_browser = _fake_launch
    try:
        result = loop.run()
    finally:
        loop_module.launch_browser = original

    assert result.status == LayerStatus.PASSED
    assert stubborn.killed is True


def test_relaunch_terminates_previous_browser(tmp_path: Path) -> None:
    responses = [
        json.dumps(
            {
                "thought": "launch",
                "action": {"type": "launch", "url": "http://localhost:3000/"},
            }
        ),
        json.dumps(
            {
                "thought": "launch again",
                "action": {"type": "launch", "url": "http://localhost:3000/tasks"},
            }
        ),
        json.dumps(
            {
                "thought": "done",
                "action": {"type": "done", "success": True, "message": "ok"},
            }
        ),
    ]

    import finalstrike.computer_use.loop as loop_module

    processes: list[_FakeBrowserProcess] = []

    def _fake_launch(url: str, *, browser: BrowserKind) -> _FakeBrowserProcess:
        del browser
        process = _FakeBrowserProcess()
        processes.append(process)
        return process

    loop = ActionLoop(
        instruction="verify",
        output_dir=tmp_path,
        provider=ReplayActionProvider(responses),
        browser=BrowserKind.CHROMIUM,
        max_steps=4,
        max_action_retries=0,
        max_parse_retries=0,
        screenshot_driver=_FakeScreenshotDriver(),
        input_driver=_FakeInput(),
        ui_base_url=UI_BASE_URL,
    )

    original = loop_module.launch_browser
    loop_module.launch_browser = _fake_launch
    try:
        result = loop.run()
    finally:
        loop_module.launch_browser = original

    assert result.status == LayerStatus.PASSED
    assert len(processes) == 2
    assert processes[0].terminated is True
    assert processes[1].terminated is True


def test_cleanup_oserror_does_not_mask_successful_result(tmp_path: Path) -> None:
    responses = [
        json.dumps(
            {
                "thought": "done",
                "action": {"type": "done", "success": True, "message": "ok"},
            }
        ),
    ]

    import finalstrike.computer_use.loop as loop_module

    class _RaisingTerminateProcess(_FakeBrowserProcess):
        def terminate(self) -> None:
            raise OSError("permission denied")

    loop = ActionLoop(
        instruction="verify",
        output_dir=tmp_path,
        provider=ReplayActionProvider(responses),
        browser=BrowserKind.CHROMIUM,
        max_steps=1,
        max_action_retries=0,
        max_parse_retries=0,
        screenshot_driver=_FakeScreenshotDriver(),
        input_driver=_FakeInput(),
        ui_base_url=UI_BASE_URL,
    )
    loop._browser_process = _RaisingTerminateProcess()

    result = loop.run()
    assert result.status == LayerStatus.PASSED
    assert loop._browser_process is None
