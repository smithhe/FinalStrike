"""Tests for computer-use page title helpers and loop overrides."""

from __future__ import annotations

import json
from pathlib import Path

from finalstrike.computer_use.loop import ActionLoop, ReplayActionProvider
from finalstrike.computer_use.platform.a11y import AccessibilitySnapshot
from finalstrike.computer_use.platform.session import SessionType
from finalstrike.computer_use.title import (
    expected_title_from_instruction,
    wait_for_window_title,
    window_list_includes_title,
)
from finalstrike.config.models import BrowserKind, LayerStatus
from tests.test_p6_computer_use import (
    _FakeBrowserProcess,
    _FakeInput,
    _FakeScreenshotDriver,
)


class _SequenceA11yDriver:
    def __init__(self, window_sequences: list[list[str]]) -> None:
        self._sequences = list(window_sequences)
        self._index = 0

    def capture(self) -> AccessibilitySnapshot:
        if self._index < len(self._sequences):
            windows = self._sequences[self._index]
            self._index += 1
        else:
            windows = self._sequences[-1] if self._sequences else []
        return AccessibilitySnapshot(session=SessionType.X11, windows=windows)


def test_expected_title_from_instruction() -> None:
    assert (
        expected_title_from_instruction(
            'Open http://localhost:3000/ and verify the page title is "Sample App"'
        )
        == "Sample App"
    )
    assert expected_title_from_instruction("click the button") is None


def test_window_list_includes_title_substring() -> None:
    assert window_list_includes_title(["localhost - Chromium"], "localhost")
    assert window_list_includes_title(["Sample App - Chromium"], "Sample App")
    assert not window_list_includes_title(["localhost - Chromium"], "Sample App")


def test_wait_for_window_title_polls_until_match() -> None:
    driver = _SequenceA11yDriver(
        [
            ["localhost - Chromium"],
            ["localhost - Chromium"],
            ["Sample App - Chromium"],
        ]
    )
    assert wait_for_window_title(
        driver,
        "Sample App",
        timeout=2.0,
        poll_interval=0.01,
    )


def test_done_failure_overridden_when_wm_title_matches(tmp_path: Path) -> None:
    instruction = (
        'Open http://localhost:3000/ and verify the page title is "Sample App"'
    )
    responses = [
        json.dumps(
            {
                "thought": "launch",
                "action": {"type": "launch", "url": "http://localhost:3000/"},
            }
        ),
        json.dumps(
            {
                "thought": "still loading",
                "action": {"type": "wait", "seconds": 0.01},
            }
        ),
        json.dumps(
            {
                "thought": "vision still sees localhost",
                "action": {
                    "type": "done",
                    "success": False,
                    "message": 'Page title is not "Sample App"; it appears to be "localhost".',
                },
            }
        ),
    ]

    import finalstrike.computer_use.loop as loop_module

    launched: list[str] = []

    def _fake_launch(url: str, *, browser: BrowserKind) -> object:
        del browser
        launched.append(url)
        return _FakeBrowserProcess()

    a11y = _SequenceA11yDriver(
        [
            [],
            ["localhost - Chromium"],
            ["Sample App - Chromium"],
            ["Sample App - Chromium"],
        ]
    )

    loop = ActionLoop(
        instruction=instruction,
        output_dir=tmp_path,
        provider=ReplayActionProvider(responses),
        browser=BrowserKind.CHROMIUM,
        max_steps=5,
        max_action_retries=0,
        max_parse_retries=0,
        screenshot_driver=_FakeScreenshotDriver(),
        input_driver=_FakeInput(),
        a11y_driver=a11y,
        title_load_timeout=0.5,
        ui_base_url="http://localhost:3000",
    )

    original = loop_module.launch_browser
    loop_module.launch_browser = _fake_launch
    try:
        result = loop.run()
    finally:
        loop_module.launch_browser = original

    assert result.status == LayerStatus.PASSED
    assert result.error is None
    assert launched == ["http://localhost:3000/"]
