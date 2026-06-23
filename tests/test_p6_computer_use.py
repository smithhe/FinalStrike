"""P6 computer-use unit tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from finalstrike.computer_use.actions import (
    ActionPayload,
    ComputerActionResponse,
    action_summary,
    parse_action_response,
)
from finalstrike.computer_use.browser import (
    BrowserLaunchError,
    browser_available,
    resolve_browser_binary,
)
from finalstrike.computer_use.config import resolve_computer_use_llm
from finalstrike.computer_use.loop import ActionLoop, ReplayActionProvider
from finalstrike.computer_use.platform.session import SessionType, detect_session_type
from finalstrike.computer_use.prompt import action_prompt_version, build_action_messages
from finalstrike.config.loader import load_config
from finalstrike.config.models import BrowserKind, LayerStatus
from tests.conftest import FIXTURE_REPO

UI_BASE_URL = "http://localhost:3000"


def test_parse_launch_action() -> None:
    raw = json.dumps(
        {
            "thought": "open page",
            "action": {"type": "launch", "url": "http://localhost:3000/"},
        }
    )
    parsed = parse_action_response(raw)
    assert parsed.action.type == "launch"
    assert parsed.action.url == "http://localhost:3000/"


def test_parse_action_from_markdown_fence() -> None:
    raw = """```json
{"thought": "open page", "action": {"type": "launch", "url": "http://localhost:3000/"}}
```"""
    parsed = parse_action_response(raw)
    assert parsed.action.type == "launch"


def test_parse_flat_action_shape() -> None:
    raw = json.dumps(
        {
            "thought": "open page",
            "type": "launch",
            "url": "http://localhost:3000/",
        }
    )
    parsed = parse_action_response(raw)
    assert parsed.action.type == "launch"
    assert parsed.action.url == "http://localhost:3000/"


def test_parse_action_ignores_extra_fields() -> None:
    raw = json.dumps(
        {
            "thought": "open page",
            "reasoning": "extra field from model",
            "action": {
                "type": "launch",
                "url": "http://localhost:3000/",
                "confidence": 0.99,
            },
        }
    )
    parsed = parse_action_response(raw)
    assert parsed.action.type == "launch"


def test_parse_done_action_requires_success() -> None:
    with pytest.raises(ValueError, match="invalid computer-use action JSON"):
        parse_action_response(
            json.dumps({"thought": "done", "action": {"type": "done"}})
        )


def test_action_summary_labels() -> None:
    assert action_summary(ActionPayload(type="launch", url="http://x")) == "launch(http://x)"
    assert action_summary(ActionPayload(type="done", success=True)) == "done(success=True)"


def test_resolve_computer_use_llm_falls_back_to_planner(tmp_path: Path) -> None:
    (tmp_path / "finalstrike.yaml").write_text(
        """
version: "1"
project:
  name: computer-use-config
llm:
  provider: openai_compat
  base_url: http://localhost:11434/v1
  model: unit-test-model
""".strip()
        + "\n",
        encoding="utf-8",
    )
    config = load_config(tmp_path)
    assert resolve_computer_use_llm(config) is config.llm


def test_build_action_messages_include_image_part() -> None:
    messages = build_action_messages(
        instruction="verify title",
        screenshot_data_url="data:image/png;base64,abc",
        a11y_summary="session=x11",
        history=[],
    )
    assert messages[0]["role"] == "system"
    user = messages[1]
    assert user["role"] == "user"
    content = user["content"]
    assert isinstance(content, list)
    assert any(part.get("type") == "image_url" for part in content)


def test_replay_action_provider_returns_responses_in_order() -> None:
    provider = ReplayActionProvider(
        [
            json.dumps(
                {
                    "thought": "done",
                    "action": {"type": "done", "success": True, "message": "ok"},
                }
            )
        ]
    )
    raw = provider.chat_completion_multimodal([])
    parsed = parse_action_response(raw)
    assert parsed.action.success is True
    assert provider.calls == 1


class _FakeScreenshot:
    def __init__(self) -> None:
        self.png_bytes = b"fakepng"
        self.width = 10
        self.height = 10

    def save(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.png_bytes)
        return path

    def as_data_url(self) -> str:
        return "data:image/png;base64,ZmFrZQ=="


class _FakeScreenshotDriver:
    def capture(self) -> _FakeScreenshot:
        return _FakeScreenshot()


class _FakeBrowserProcess:
    def __init__(self) -> None:
        self.terminated = False

    def poll(self) -> None:
        return None

    def terminate(self) -> None:
        self.terminated = True

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        return 0


class _FakeInput:
    def __init__(self) -> None:
        self.launched: list[str] = []

    def click(self, x: int, y: int) -> None:
        del x, y

    def type_text(self, text: str) -> None:
        del text

    def key(self, combo: str) -> None:
        del combo

    def scroll(self, direction: str, amount: int = 3) -> None:
        del direction, amount

    def focus_window(self, title_substring: str) -> None:
        del title_substring


class _SequenceFlakyClickInput(_FakeInput):
    def __init__(self, fail_pattern: list[bool]) -> None:
        super().__init__()
        self._fail_pattern = list(fail_pattern)
        self._click_calls = 0

    def click(self, x: int, y: int) -> None:
        should_fail = (
            self._click_calls < len(self._fail_pattern)
            and self._fail_pattern[self._click_calls]
        )
        self._click_calls += 1
        if should_fail:
            raise RuntimeError("simulated transient click failure")
        super().click(x, y)


def test_action_loop_retries_invalid_json_on_same_step(tmp_path: Path) -> None:
    valid = json.dumps(
        {
            "thought": "done",
            "action": {"type": "done", "success": True, "message": "ok"},
        }
    )

    class _FlakyProvider:
        def __init__(self) -> None:
            self.calls = 0

        def chat_completion_multimodal(
            self,
            messages: list[dict[str, object]],
            *,
            temperature: float = 0.2,
            json_mode: bool = True,
        ) -> str:
            del temperature, json_mode
            self.calls += 1
            if self.calls == 1:
                return "not json"
            user = messages[1]
            content = user["content"]
            assert isinstance(content, list)
            text = next(part["text"] for part in content if part.get("type") == "text")
            assert "Previous attempt failed validation" in text
            return valid

    loop = ActionLoop(
        instruction="verify title",
        output_dir=tmp_path,
        provider=_FlakyProvider(),
        browser=BrowserKind.CHROMIUM,
        max_steps=3,
        max_action_retries=2,
        max_parse_retries=2,
        screenshot_driver=_FakeScreenshotDriver(),
        input_driver=_FakeInput(),
        ui_base_url=UI_BASE_URL,
    )
    result = loop.run()
    assert result.status == LayerStatus.PASSED
    assert len(result.screenshots) == 1
    assert len(result.steps) == 1


def test_action_loop_surfaces_llm_error(tmp_path: Path) -> None:
    from finalstrike.providers.openai_compat import LLMProviderError

    class _RaisingProvider:
        def chat_completion_multimodal(
            self,
            messages: list[dict[str, object]],
            *,
            temperature: float = 0.2,
            json_mode: bool = True,
        ) -> str:
            del messages, temperature, json_mode
            raise LLMProviderError("vision model rejected image input")

    loop = ActionLoop(
        instruction="verify title",
        output_dir=tmp_path,
        provider=_RaisingProvider(),
        browser=BrowserKind.CHROMIUM,
        max_steps=3,
        max_action_retries=1,
        max_parse_retries=1,
        screenshot_driver=_FakeScreenshotDriver(),
        input_driver=_FakeInput(),
        ui_base_url=UI_BASE_URL,
    )
    result = loop.run()
    assert result.status == LayerStatus.FAILED
    assert result.error is not None
    assert "vision model rejected image input" in result.error
    assert len(result.screenshots) == 1


def test_action_loop_replay_cassette_completes(tmp_path: Path) -> None:
    responses = [
        json.dumps(
            {
                "thought": "launch",
                "action": {"type": "launch", "url": "http://localhost:3000/"},
            }
        ),
        json.dumps(
            {
                "thought": "wait",
                "action": {"type": "wait", "seconds": 0.01},
            }
        ),
        json.dumps(
            {
                "thought": "verified",
                "action": {
                    "type": "done",
                    "success": True,
                    "message": "Page title is Sample App",
                },
            }
        ),
    ]

    loop = ActionLoop(
        instruction='verify title "Sample App"',
        output_dir=tmp_path,
        provider=ReplayActionProvider(responses),
        browser=BrowserKind.CHROMIUM,
        max_steps=5,
        max_action_retries=0,
        max_parse_retries=0,
        screenshot_driver=_FakeScreenshotDriver(),
        input_driver=_FakeInput(),
        ui_base_url=UI_BASE_URL,
    )

    # Monkeypatch launch_browser to avoid real browser in unit test
    import finalstrike.computer_use.loop as loop_module

    launched: list[str] = []
    browser_processes: list[_FakeBrowserProcess] = []

    def _fake_launch(url: str, *, browser: BrowserKind) -> _FakeBrowserProcess:
        del browser
        launched.append(url)
        process = _FakeBrowserProcess()
        browser_processes.append(process)
        return process

    original = loop_module.launch_browser
    loop_module.launch_browser = _fake_launch
    try:
        result = loop.run()
    finally:
        loop_module.launch_browser = original

    assert result.status == LayerStatus.PASSED
    assert len(result.steps) == 3
    assert launched == ["http://localhost:3000/"]
    assert browser_processes[0].terminated is True
    assert (tmp_path / "screenshots" / "step-000.png").is_file()


def test_validate_launch_url_rejects_non_http(tmp_path: Path) -> None:
    from finalstrike.computer_use.urls import validate_launch_url

    with pytest.raises(ValueError, match="http or https"):
        validate_launch_url("file:///etc/passwd", ui_base_url=UI_BASE_URL)


def test_validate_launch_url_allows_loopback_alias() -> None:
    from finalstrike.computer_use.urls import validate_launch_url

    assert (
        validate_launch_url(
            "http://127.0.0.1:3000/",
            ui_base_url="http://localhost:3000",
        )
        == "http://127.0.0.1:3000/"
    )


def test_validate_launch_url_rejects_foreign_host() -> None:
    from finalstrike.computer_use.urls import validate_launch_url

    with pytest.raises(ValueError, match="outside configured"):
        validate_launch_url("http://evil.example/", ui_base_url=UI_BASE_URL)


def test_action_loop_per_step_retries_reset_between_steps(tmp_path: Path) -> None:
    """Each step gets its own action-retry budget (not a global pool)."""
    responses = [
        json.dumps(
            {
                "thought": "click",
                "action": {"type": "click", "x": 5, "y": 5},
            }
        ),
        json.dumps(
            {
                "thought": "click again",
                "action": {"type": "click", "x": 5, "y": 5},
            }
        ),
        json.dumps(
            {
                "thought": "done",
                "action": {"type": "done", "success": True, "message": "ok"},
            }
        ),
    ]
    provider = ReplayActionProvider(responses)

    loop = ActionLoop(
        instruction="verify",
        output_dir=tmp_path,
        provider=provider,
        browser=BrowserKind.CHROMIUM,
        max_steps=5,
        max_action_retries=1,
        max_parse_retries=0,
        screenshot_driver=_FakeScreenshotDriver(),
        input_driver=_SequenceFlakyClickInput([True, False, True, False]),
        ui_base_url=UI_BASE_URL,
    )
    result = loop.run()
    assert result.status == LayerStatus.PASSED
    assert provider.calls == 3
    assert len(result.steps) == 3
    assert result.screenshots == [
        "screenshots/step-000.png",
        "screenshots/step-001.png",
        "screenshots/step-002.png",
    ]


def test_action_loop_action_retry_does_not_duplicate_steps(tmp_path: Path) -> None:
    responses = [
        json.dumps(
            {
                "thought": "click",
                "action": {"type": "click", "x": 5, "y": 5},
            }
        ),
        json.dumps(
            {
                "thought": "done",
                "action": {"type": "done", "success": True, "message": "ok"},
            }
        ),
    ]
    provider = ReplayActionProvider(responses)

    loop = ActionLoop(
        instruction="verify",
        output_dir=tmp_path,
        provider=provider,
        browser=BrowserKind.CHROMIUM,
        max_steps=3,
        max_action_retries=1,
        max_parse_retries=0,
        screenshot_driver=_FakeScreenshotDriver(),
        input_driver=_SequenceFlakyClickInput([True, False]),
        ui_base_url=UI_BASE_URL,
    )
    result = loop.run()
    assert result.status == LayerStatus.PASSED
    assert provider.calls == 2
    assert len(result.steps) == 2
    assert len(result.screenshots) == 2
    assert all(step.status == LayerStatus.PASSED for step in result.steps)


def test_action_retry_does_not_reinvoke_llm(tmp_path: Path) -> None:
    responses = [
        json.dumps(
            {
                "thought": "click",
                "action": {"type": "click", "x": 5, "y": 5},
            }
        ),
        json.dumps(
            {
                "thought": "done",
                "action": {"type": "done", "success": True, "message": "ok"},
            }
        ),
    ]
    provider = ReplayActionProvider(responses)

    loop = ActionLoop(
        instruction="verify",
        output_dir=tmp_path,
        provider=provider,
        browser=BrowserKind.CHROMIUM,
        max_steps=3,
        max_action_retries=1,
        max_parse_retries=0,
        screenshot_driver=_FakeScreenshotDriver(),
        input_driver=_SequenceFlakyClickInput([True, False]),
        ui_base_url=UI_BASE_URL,
    )
    result = loop.run()
    assert result.status == LayerStatus.PASSED
    assert provider.calls == 2


def test_click_rejected_when_screenshot_dimensions_unknown(tmp_path: Path) -> None:
    class _ZeroSizeScreenshot(_FakeScreenshot):
        def __init__(self) -> None:
            super().__init__()
            self.width = 0
            self.height = 0

    class _ZeroSizeScreenshotDriver(_FakeScreenshotDriver):
        def capture(self) -> _FakeScreenshot:
            return _ZeroSizeScreenshot()

    responses = [
        json.dumps(
            {
                "thought": "click",
                "action": {"type": "click", "x": 1, "y": 1},
            }
        ),
    ]
    loop = ActionLoop(
        instruction="verify",
        output_dir=tmp_path,
        provider=ReplayActionProvider(responses),
        browser=BrowserKind.CHROMIUM,
        max_steps=2,
        max_action_retries=0,
        max_parse_retries=0,
        screenshot_driver=_ZeroSizeScreenshotDriver(),
        input_driver=_FakeInput(),
        ui_base_url=UI_BASE_URL,
    )
    result = loop.run()
    assert result.status == LayerStatus.FAILED
    assert result.error is not None
    assert "dimensions unknown" in result.error


def test_build_action_messages_include_configured_ui() -> None:
    messages = build_action_messages(
        instruction="verify title",
        screenshot_data_url="data:image/png;base64,abc",
        a11y_summary="session=x11",
        history=[],
        ui_base_url=UI_BASE_URL,
        smoke_route="/",
    )
    user = messages[1]
    content = user["content"]
    assert isinstance(content, list)
    text = next(part["text"] for part in content if part.get("type") == "text")
    assert "canonical_url: http://localhost:3000/" in text


def test_png_dimensions_from_header() -> None:
    from finalstrike.computer_use.platform.screenshot import _png_dimensions

    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        + (120).to_bytes(4, "big")
        + (80).to_bytes(4, "big")
        + b"\x00" * 100
    )
    assert _png_dimensions(png) == (120, 80)


def test_detect_session_type_returns_enum() -> None:
    session = detect_session_type()
    assert isinstance(session, SessionType)


def test_browser_resolution_reports_chrome_or_chromium() -> None:
    if not browser_available(BrowserKind.CHROMIUM):
        pytest.skip("Chrome/Chromium not installed on this host")
    path = resolve_browser_binary(BrowserKind.CHROMIUM)
    assert path


def test_invalid_browser_kind_rejected_by_model() -> None:
    from pydantic import ValidationError

    from finalstrike.config.models import UIConfig

    with pytest.raises(ValidationError):
        UIConfig.model_validate(
            {"base_url": "http://localhost:3000", "browser": "firefox"}
        )


def test_action_prompt_version_stable() -> None:
    assert len(action_prompt_version()) == 16
