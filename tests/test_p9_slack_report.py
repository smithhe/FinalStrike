"""Tests for P9 Slack bot reporter."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from finalstrike.config.models import (
    APICheckResult,
    APILayerResult,
    BuildCommandResult,
    BuildLayerResult,
    EnvLayerResult,
    LayerStatus,
    PlanGap,
    RunResult,
    RunStatus,
    SlackConfig,
    TerminalCommandResult,
    TerminalLayerResult,
    UIStepResult,
    UILayerResult,
    UIScenarioResult,
)
from finalstrike.reporters.slack import (
    SlackPostStatus,
    SlackReporterError,
    SlackWebClient,
    _build_message_blocks,
    _select_upload_files,
    assess_slack,
    maybe_post_slack_report,
    post_slack_report,
    resolve_bot_token,
)

from tests.test_p8_html_report import FIXTURE_RUN, _load_fixture_result


class RecordingSlackClient:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []
        self.uploads: list[tuple[Path, str, str]] = []

    def post_message(
        self,
        *,
        channel_id: str,
        blocks: list[dict[str, Any]] | None = None,
        text: str | None = None,
    ) -> dict[str, Any]:
        self.messages.append(
            {"channel_id": channel_id, "blocks": blocks, "text": text}
        )
        return {"ok": True}

    def upload_file(self, *, path: Path, channel_id: str, title: str) -> dict[str, Any]:
        self.uploads.append((path, channel_id, title))
        return {"ok": True}


def test_resolve_bot_token_prefers_secrets() -> None:
    token = resolve_bot_token(
        {"SLACK_BOT_TOKEN": "xoxb-secret"},
        secret_name="SLACK_BOT_TOKEN",
    )
    assert token == "xoxb-secret"


def test_resolve_bot_token_missing_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    assert resolve_bot_token({}, secret_name="SLACK_BOT_TOKEN") is None


def test_resolve_bot_token_falls_back_to_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-from-env")
    assert resolve_bot_token({}, secret_name="SLACK_BOT_TOKEN") == "xoxb-from-env"


def test_assess_slack_without_config() -> None:
    status = assess_slack(None, {})
    assert not status.ready
    assert "not configured" in status.detail


def test_assess_slack_with_token() -> None:
    config = SlackConfig(bot_token_secret="SLACK_BOT_TOKEN", channel_id="C0123")
    status = assess_slack(config, {"SLACK_BOT_TOKEN": "xoxb-test"})
    assert status.ready
    assert "C0123" in status.detail


def test_build_message_blocks_includes_layers_and_gaps() -> None:
    result = _load_fixture_result()
    blocks, _ = _build_message_blocks(result, artifact_dir=FIXTURE_RUN, secrets={})
    rendered = str(blocks)
    assert "partial" in rendered
    assert "138 passed" in rendered
    assert "1/1 checks passed" in rendered
    assert "OAuth login" in rendered
    assert "report.html" in rendered


def test_select_upload_files_prefers_video_and_screenshots(tmp_path: Path) -> None:
    result = _load_fixture_result()
    screenshot = tmp_path / "screenshots" / "step-001.png"
    screenshot.parent.mkdir(parents=True)
    screenshot.write_bytes(b"png")
    video = tmp_path / "desktop.mp4"
    video.write_bytes(b"mp4")

    selected = _select_upload_files(result, tmp_path)
    titles = [title for _, title in selected]
    assert "Desktop recording" in titles
    assert "First screenshot" in titles


def test_post_slack_report_skips_without_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    config = SlackConfig(bot_token_secret="SLACK_BOT_TOKEN", channel_id="C0123")
    result = RunResult(run_id="run-1", repo="/tmp/repo", status=RunStatus.PASSED)
    post_result = post_slack_report(
        result,
        artifact_dir=Path("/tmp"),
        config=config,
        secrets={},
    )
    assert post_result.status == SlackPostStatus.SKIPPED
    assert "not found" in post_result.detail


def test_post_slack_report_posts_message_and_uploads(tmp_path: Path) -> None:
    result = _load_fixture_result()
    screenshot = tmp_path / "screenshots" / "step-001.png"
    screenshot.parent.mkdir(parents=True)
    screenshot.write_bytes(b"png")
    (tmp_path / "desktop.mp4").write_bytes(b"mp4")

    client = RecordingSlackClient()
    config = SlackConfig(bot_token_secret="SLACK_BOT_TOKEN", channel_id="C0123")
    post_result = post_slack_report(
        result,
        artifact_dir=tmp_path,
        config=config,
        secrets={"SLACK_BOT_TOKEN": "xoxb-test-token"},
        client=client,
    )

    assert post_result.status == SlackPostStatus.POSTED
    assert len(client.messages) == 1
    assert client.messages[0]["channel_id"] == "C0123"
    assert client.uploads
    assert any(title == "Desktop recording" for _, _, title in client.uploads)


def test_post_slack_report_redacts_token_on_api_failure(tmp_path: Path) -> None:
    class FailingClient:
        def post_message(self, **kwargs: Any) -> dict[str, Any]:
            raise SlackReporterError("Slack API chat.postMessage failed: invalid_auth xoxb-test-token")

        def upload_file(self, **kwargs: Any) -> dict[str, Any]:
            return {"ok": True}

    config = SlackConfig(bot_token_secret="SLACK_BOT_TOKEN", channel_id="C0123")
    result = RunResult(run_id="run-1", repo="/tmp/repo", status=RunStatus.PASSED)
    post_result = post_slack_report(
        result,
        artifact_dir=tmp_path,
        config=config,
        secrets={"SLACK_BOT_TOKEN": "xoxb-test-token"},
        client=FailingClient(),
    )
    assert post_result.status == SlackPostStatus.FAILED
    assert "xoxb-test-token" not in post_result.detail
    assert "***" in post_result.detail


def test_maybe_post_slack_report_disabled_by_flag(tmp_path: Path) -> None:
    config = SlackConfig(bot_token_secret="SLACK_BOT_TOKEN", channel_id="C0123")
    result = RunResult(run_id="run-1", repo="/tmp/repo", status=RunStatus.PASSED)
    assert (
        maybe_post_slack_report(
            result,
            artifact_dir=tmp_path,
            config=config,
            secrets={"SLACK_BOT_TOKEN": "xoxb-test-token"},
            enabled=False,
        )
        is None
    )


def test_maybe_post_slack_report_without_config(tmp_path: Path) -> None:
    result = RunResult(run_id="run-1", repo="/tmp/repo", status=RunStatus.PASSED)
    assert (
        maybe_post_slack_report(
            result,
            artifact_dir=tmp_path,
            config=None,
            secrets={},
        )
        is None
    )


def test_slack_web_client_raises_on_api_error() -> None:
    client = SlackWebClient(token="xoxb-test")
    with patch.object(client._client, "post") as mock_post:
        mock_post.return_value = type(
            "Response",
            (),
            {
                "raise_for_status": lambda self: None,
                "json": lambda self: {"ok": False, "error": "invalid_auth"},
            },
        )()
        with pytest.raises(SlackReporterError, match="invalid_auth"):
            client.post_message(channel_id="C0123", text="hello")


def test_ui_failure_screenshot_selected(tmp_path: Path) -> None:
    first = tmp_path / "screenshots" / "step-001.png"
    failed = tmp_path / "screenshots" / "step-002.png"
    last = tmp_path / "screenshots" / "step-003.png"
    first.parent.mkdir(parents=True)
    first.write_bytes(b"first")
    failed.write_bytes(b"failed")
    last.write_bytes(b"last")

    result = RunResult(
        run_id="run-ui",
        repo=str(tmp_path),
        status=RunStatus.FAILED,
        layers={
            "ui": UILayerResult(
                status=LayerStatus.FAILED,
                scenarios=[UIScenarioResult(id="s1", status=LayerStatus.FAILED)],
                steps=[
                    UIStepResult(
                        step_index=0,
                        action="open page",
                        screenshot="screenshots/step-001.png",
                        status=LayerStatus.PASSED,
                    ),
                    UIStepResult(
                        step_index=1,
                        action="click broken button",
                        screenshot="screenshots/step-002.png",
                        status=LayerStatus.FAILED,
                    ),
                    UIStepResult(
                        step_index=2,
                        action="inspect final state",
                        screenshot="screenshots/step-003.png",
                        status=LayerStatus.PASSED,
                    ),
                ],
                error="button missing",
            )
        },
        artifacts={
            "screenshots": [
                "screenshots/step-001.png",
                "screenshots/step-002.png",
                "screenshots/step-003.png",
            ]
        },
    )

    selected = _select_upload_files(result, tmp_path)
    titles = [title for _, title in selected]
    assert "Failure screenshot" in titles
    assert "First screenshot" in titles
    assert "Final screenshot" in titles


def test_layer_summary_all_layers() -> None:
    result = RunResult(
        run_id="full-run",
        repo="/tmp/repo",
        status=RunStatus.PASSED,
        layers={
            "env": EnvLayerResult(status=LayerStatus.PASSED, duration_ms=100),
            "build": BuildLayerResult(
                status=LayerStatus.PASSED,
                commands=[
                    BuildCommandResult(
                        name="build",
                        status=LayerStatus.PASSED,
                        exit_code=0,
                        duration_ms=50,
                    )
                ],
            ),
            "terminal": TerminalLayerResult(
                status=LayerStatus.PASSED,
                commands=[
                    TerminalCommandResult(
                        name="pytest",
                        status=LayerStatus.PASSED,
                        exit_code=0,
                        duration_ms=80,
                        total_passed=3,
                        total_failed=1,
                    )
                ],
                total_passed=3,
                total_failed=1,
            ),
            "api": APILayerResult(
                status=LayerStatus.PASSED,
                checks=[
                    APICheckResult(
                        method="GET",
                        path="/health",
                        status=LayerStatus.PASSED,
                    ),
                    APICheckResult(
                        method="GET",
                        path="/missing",
                        status=LayerStatus.FAILED,
                    ),
                ],
            ),
            "ui": UILayerResult(
                status=LayerStatus.PASSED,
                scenarios=[UIScenarioResult(id="s1", status=LayerStatus.PASSED)],
                steps=[
                    UIStepResult(
                        step_index=0,
                        action="open page",
                        status=LayerStatus.PASSED,
                    )
                ],
            ),
        },
        gaps=[PlanGap(item="OAuth", reason="out of scope")],
    )
    blocks, _ = _build_message_blocks(result, artifact_dir=Path("/tmp"), secrets={})
    rendered = str(blocks)
    assert "*env:* passed" in rendered
    assert "*build:* passed" in rendered
    assert "3 passed, 1 failed" in rendered
    assert "1/2 checks passed" in rendered
    assert "1 scenarios, 1 steps" in rendered
