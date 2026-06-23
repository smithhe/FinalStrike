"""Computer-use action loop: screenshot → LLM action → OS input."""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from finalstrike.computer_use.actions import (
    ActionPayload,
    action_summary,
    parse_action_response,
)
from finalstrike.computer_use.browser import BrowserLaunchError, launch_browser
from finalstrike.computer_use.platform.a11y import AccessibilityDriver
from finalstrike.computer_use.platform.input import InputDriver, create_input_driver
from finalstrike.computer_use.platform.screenshot import Screenshot, ScreenshotDriver
from finalstrike.computer_use.prompt import (
    build_action_messages,
    summarize_completed_action,
)
from finalstrike.computer_use.title import (
    expected_title_from_instruction,
    wait_for_window_title,
    window_list_includes_title,
)
from finalstrike.computer_use.urls import validate_launch_url
from finalstrike.config.models import BrowserKind, LayerStatus, UIStepResult
from finalstrike.providers.openai_compat import LLMProviderError


class ActionLLMProvider(Protocol):
    def chat_completion_multimodal(
        self,
        messages: list[dict[str, object]],
        *,
        temperature: float = 0.2,
        json_mode: bool = True,
    ) -> str: ...


@dataclass
class ActionLoopResult:
    status: LayerStatus
    steps: list[UIStepResult] = field(default_factory=list)
    screenshots: list[str] = field(default_factory=list)
    error: str | None = None


class ActionLoop:
    """Execute a single UI instruction via screenshot/action iterations."""

    def __init__(
        self,
        *,
        instruction: str,
        output_dir: Path,
        provider: ActionLLMProvider,
        browser: BrowserKind,
        max_steps: int,
        max_retries: int,
        ui_base_url: str | None = None,
        smoke_route: str = "/",
        screenshot_driver: ScreenshotDriver | None = None,
        a11y_driver: AccessibilityDriver | None = None,
        input_driver: InputDriver | None = None,
        title_load_timeout: float = 10.0,
    ) -> None:
        self.instruction = instruction
        self.output_dir = output_dir
        self.provider = provider
        self.browser = browser
        self.max_steps = max_steps
        self.max_retries = max_retries
        self.ui_base_url = ui_base_url
        self.smoke_route = smoke_route
        self._title_load_timeout = title_load_timeout
        self._screenshot_driver = screenshot_driver or ScreenshotDriver()
        self._a11y_driver = a11y_driver or AccessibilityDriver()
        self._input_driver = input_driver
        self._history: list[str] = []
        self._browser_process: subprocess.Popen[bytes] | None = None

    def run(self) -> ActionLoopResult:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        try:
            return self._run_loop()
        finally:
            self._cleanup_browser()

    def _run_loop(self) -> ActionLoopResult:
        steps: list[UIStepResult] = []
        screenshots: list[str] = []

        step_index = 0
        step_action_retries = 0
        while step_index < self.max_steps:
            screenshot = self._screenshot_driver.capture()
            rel_name = f"screenshots/step-{step_index:03d}.png"
            abs_path = self.output_dir / rel_name
            screenshot.save(abs_path)
            if step_index < len(screenshots):
                screenshots[step_index] = rel_name
            else:
                screenshots.append(rel_name)

            a11y = self._a11y_driver.capture()
            validation_error: str | None = None
            parsed = None
            for attempt in range(self.max_retries + 1):
                messages = build_action_messages(
                    instruction=self.instruction,
                    screenshot_data_url=screenshot.as_data_url(),
                    a11y_summary=a11y.summary(),
                    history=self._history,
                    validation_error=validation_error,
                    ui_base_url=self.ui_base_url,
                    smoke_route=self.smoke_route,
                )
                try:
                    raw = self.provider.chat_completion_multimodal(
                        messages,
                        temperature=0.2,
                        json_mode=True,
                    )
                    parsed = parse_action_response(raw)
                    break
                except (LLMProviderError, ValueError) as exc:
                    validation_error = str(exc)
                    if attempt >= self.max_retries:
                        return ActionLoopResult(
                            status=LayerStatus.FAILED,
                            steps=steps,
                            screenshots=screenshots,
                            error=validation_error,
                        )

            assert parsed is not None
            action = parsed.action
            label = action_summary(action)

            try:
                self._execute_action(action, screenshot=screenshot)
            except (
                RuntimeError,
                BrowserLaunchError,
                NotImplementedError,
                ValueError,
            ) as exc:
                if step_action_retries < self.max_retries:
                    step_action_retries += 1
                    self._history.append(f"{label} failed: {exc}")
                    continue
                steps.append(
                    UIStepResult(
                        step_index=step_index,
                        action=label,
                        screenshot=rel_name,
                        status=LayerStatus.FAILED,
                    )
                )
                return ActionLoopResult(
                    status=LayerStatus.FAILED,
                    steps=steps,
                    screenshots=screenshots,
                    error=str(exc),
                )

            step_action_retries = 0
            steps.append(
                UIStepResult(
                    step_index=step_index,
                    action=label,
                    screenshot=rel_name,
                    status=LayerStatus.PASSED,
                )
            )
            self._history.append(summarize_completed_action(action))
            step_index += 1

            if action.type == "done":
                success = bool(action.success)
                message = action.message
                expected_title = expected_title_from_instruction(self.instruction)
                if expected_title and window_list_includes_title(
                    self._a11y_driver.capture().windows,
                    expected_title,
                ):
                    success = True
                    if not action.success:
                        message = (
                            f'Page title verified via window manager: "{expected_title}"'
                        )
                status = LayerStatus.PASSED if success else LayerStatus.FAILED
                return ActionLoopResult(
                    status=status,
                    steps=steps,
                    screenshots=screenshots,
                    error=None if success else (message or "verification failed"),
                )

        return ActionLoopResult(
            status=LayerStatus.FAILED,
            steps=steps,
            screenshots=screenshots,
            error=f"exceeded max_ui_steps ({self.max_steps})",
        )

    def _cleanup_browser(self) -> None:
        process = self._browser_process
        if process is None:
            return
        self._browser_process = None
        if process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)

    def _input(self) -> InputDriver:
        if self._input_driver is None:
            self._input_driver = create_input_driver()
        return self._input_driver

    def _execute_action(self, action: ActionPayload, *, screenshot: Screenshot) -> None:
        if action.type == "launch":
            assert action.url is not None
            if self.ui_base_url is None:
                raise ValueError(
                    "launch actions require ui.base_url in finalstrike.yaml"
                )
            url = validate_launch_url(action.url, ui_base_url=self.ui_base_url)
            self._browser_process = launch_browser(
                url,
                browser=self.browser,
            )
            expected_title = expected_title_from_instruction(self.instruction)
            if expected_title:
                wait_for_window_title(
                    self._a11y_driver,
                    expected_title,
                    timeout=self._title_load_timeout,
                )
            return

        if action.type == "click":
            assert action.x is not None and action.y is not None
            self._validate_click_coords(action.x, action.y, screenshot)
            self._input().click(action.x, action.y)
            return

        if action.type == "type":
            assert action.text is not None
            self._input().type_text(action.text)
            return

        if action.type == "key":
            assert action.combo is not None
            self._input().key(action.combo)
            return

        if action.type == "scroll":
            assert action.direction is not None
            self._input().scroll(action.direction, action.amount or 3)
            return

        if action.type == "wait":
            assert action.seconds is not None
            time.sleep(max(0.0, action.seconds))
            return

        if action.type == "focus_window":
            assert action.title is not None
            self._input().focus_window(action.title)
            return

        if action.type == "done":
            return

        raise ValueError(f"unsupported action type: {action.type}")

    @staticmethod
    def _validate_click_coords(x: int, y: int, screenshot: Screenshot) -> None:
        if screenshot.width <= 0 or screenshot.height <= 0:
            return
        if not (0 <= x < screenshot.width and 0 <= y < screenshot.height):
            raise ValueError(
                f"click ({x}, {y}) outside screenshot bounds "
                f"({screenshot.width}x{screenshot.height})"
            )


class ReplayActionProvider:
    """Replay committed action responses in order (deterministic tests)."""

    def __init__(self, responses: list[str]) -> None:
        if not responses:
            raise ValueError("action cassette must contain at least one response")
        self._responses = list(responses)
        self.calls = 0

    def chat_completion_multimodal(
        self,
        messages: list[dict[str, object]],
        *,
        temperature: float = 0.2,
        json_mode: bool = True,
    ) -> str:
        del messages, temperature, json_mode
        if self.calls >= len(self._responses):
            raise RuntimeError(
                f"action cassette exhausted after {self.calls} call(s); "
                f"expected {len(self._responses)}"
            )
        response = self._responses[self.calls]
        self.calls += 1
        return response


def serialize_action_messages(messages: list[dict[str, object]]) -> str:
    return json.dumps(messages, sort_keys=True, ensure_ascii=False)
