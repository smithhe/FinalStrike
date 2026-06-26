"""Slack bot reporter (Phase 9)."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import httpx

from finalstrike.config.models import (
    LayerStatus,
    RunResult,
    RunStatus,
    SlackConfig,
)
from finalstrike.reporters.html import REPORT_FILENAME
from finalstrike.runners.api import sanitize_response_body

SLACK_API_BASE = "https://slack.com/api"
MAX_UPLOAD_BYTES = 50 * 1024 * 1024

_STATUS_EMOJI: dict[RunStatus, str] = {
    RunStatus.PASSED: "✅",
    RunStatus.FAILED: "❌",
    RunStatus.PARTIAL: "⚠️",
}


class SlackPostStatus(str, Enum):
    POSTED = "posted"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass(frozen=True)
class SlackPostResult:
    status: SlackPostStatus
    detail: str


@dataclass(frozen=True)
class SlackStatus:
    ready: bool
    detail: str


class SlackReporterError(RuntimeError):
    """Raised when Slack API calls fail."""


def resolve_bot_token(secrets: dict[str, str], *, secret_name: str) -> str | None:
    """Resolve a Slack bot token from the secrets vault or environment."""
    for source in (secrets, os.environ):
        token = source.get(secret_name)
        if token:
            return token
    return None


def assess_slack(
    config: SlackConfig | None,
    secrets: dict[str, str],
) -> SlackStatus:
    """Return whether Slack reporting is configured and has a bot token."""
    if config is None:
        return SlackStatus(ready=False, detail="slack block not configured in finalstrike.yaml")
    token = resolve_bot_token(secrets, secret_name=config.bot_token_secret)
    if not token:
        return SlackStatus(
            ready=False,
            detail=(
                f"Missing {config.bot_token_secret} in secrets vault or environment "
                f"(channel {config.channel_id})"
            ),
        )
    if not config.channel_id.strip():
        return SlackStatus(ready=False, detail="slack.channel_id is empty")
    return SlackStatus(
        ready=True,
        detail=f"Token configured for channel {config.channel_id}",
    )


def post_slack_report(
    result: RunResult,
    *,
    artifact_dir: Path,
    config: SlackConfig,
    secrets: dict[str, str],
    client: SlackWebClient | None = None,
) -> SlackPostResult:
    """Post a run completion summary and evidence files to Slack."""
    token = resolve_bot_token(secrets, secret_name=config.bot_token_secret)
    if not token:
        return SlackPostResult(
            status=SlackPostStatus.SKIPPED,
            detail=(
                f"Slack bot token {config.bot_token_secret!r} not found; "
                "skipping Slack report"
            ),
        )

    artifact_dir = artifact_dir.resolve()
    slack_client = client or SlackWebClient(token=token)
    redaction_values = {token, *secrets.values()}

    try:
        blocks, skipped_files = _build_message_blocks(
            result,
            artifact_dir=artifact_dir,
            secrets=secrets,
        )
        slack_client.post_message(channel_id=config.channel_id, blocks=blocks)
        for file_path, title in _select_upload_files(result, artifact_dir):
            if file_path.stat().st_size > MAX_UPLOAD_BYTES:
                skipped_files.append(
                    f"{title} ({file_path.name}) exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)}MB"
                )
                continue
            slack_client.upload_file(
                path=file_path,
                channel_id=config.channel_id,
                title=title,
            )
        if skipped_files:
            slack_client.post_message(
                channel_id=config.channel_id,
                text=_format_skipped_files(skipped_files),
            )
    except SlackReporterError as exc:
        return SlackPostResult(
            status=SlackPostStatus.FAILED,
            detail=_redact_error(str(exc), redaction_values),
        )

    return SlackPostResult(status=SlackPostStatus.POSTED, detail="Posted to Slack")


def maybe_post_slack_report(
    result: RunResult,
    *,
    artifact_dir: Path,
    config: SlackConfig | None,
    secrets: dict[str, str],
    enabled: bool = True,
    client: SlackWebClient | None = None,
) -> SlackPostResult | None:
    """Post to Slack when configured and enabled; otherwise return None."""
    if not enabled or config is None:
        return None
    return post_slack_report(
        result,
        artifact_dir=artifact_dir,
        config=config,
        secrets=secrets,
        client=client,
    )


class SlackWebClient:
    """Minimal Slack Web API client backed by httpx."""

    def __init__(self, *, token: str, timeout: float = 60.0) -> None:
        self._token = token
        self._client = httpx.Client(
            base_url=SLACK_API_BASE,
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout,
        )

    def post_message(
        self,
        *,
        channel_id: str,
        blocks: list[dict[str, Any]] | None = None,
        text: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"channel": channel_id}
        if blocks is not None:
            payload["blocks"] = blocks
        if text is not None:
            payload["text"] = text
        if "text" not in payload:
            payload["text"] = "FinalStrike run report"
        return self._api("chat.postMessage", json=payload)

    def upload_file(self, *, path: Path, channel_id: str, title: str) -> dict[str, Any]:
        file_size = path.stat().st_size
        upload_info = self._api(
            "files.getUploadURLExternal",
            data={"filename": path.name, "length": str(file_size)},
        )
        upload_url = upload_info["upload_url"]
        file_id = upload_info["file_id"]
        with path.open("rb") as handle:
            response = httpx.post(
                upload_url,
                content=handle.read(),
                headers={"Content-Type": "application/octet-stream"},
                timeout=self._client.timeout,
            )
        response.raise_for_status()
        return self._api(
            "files.completeUploadExternal",
            json={
                "channel_id": channel_id,
                "files": [{"id": file_id, "title": title}],
            },
        )

    def _api(self, method: str, **kwargs: Any) -> dict[str, Any]:
        response = self._client.post(f"/{method}", **kwargs)
        response.raise_for_status()
        payload = response.json()
        if not payload.get("ok"):
            error = str(payload.get("error", "unknown_error"))
            raise SlackReporterError(f"Slack API {method} failed: {error}")
        return payload


def _build_message_blocks(
    result: RunResult,
    *,
    artifact_dir: Path,
    secrets: dict[str, str],
) -> tuple[list[dict[str, Any]], list[str]]:
    emoji = _STATUS_EMOJI.get(result.status, "❓")
    repo_name = Path(result.repo).name
    branch = result.branch or "unknown"
    duration = _format_duration(_total_duration_ms(result))
    header = (
        f"{emoji} *{result.status.value}* — {repo_name} "
        f"(`{branch}`) · run `{result.run_id}` · {duration}"
    )

    layer_lines = _layer_summary_lines(result)
    report_path = _report_path(result, artifact_dir)
    skipped_files: list[str] = []

    blocks: list[dict[str, Any]] = [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": header},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "\n".join(layer_lines)},
        },
    ]

    if result.gaps:
        gap_lines = [
            f"• *{_safe_mrkdwn(gap.item)}* — {_safe_mrkdwn(gap.reason)}"
            for gap in result.gaps
        ]
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*Gaps*\n" + "\n".join(gap_lines),
                },
            }
        )

    blocks.append(
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"HTML report: `{_safe_mrkdwn(report_path)}`",
                }
            ],
        }
    )
    return blocks, skipped_files


def _layer_summary_lines(result: RunResult) -> list[str]:
    lines: list[str] = []

    if result.layers.env is not None:
        lines.append(f"*env:* {result.layers.env.status.value}")

    if result.layers.build is not None:
        lines.append(f"*build:* {result.layers.build.status.value}")

    if result.layers.terminal is not None:
        terminal = result.layers.terminal
        lines.append(
            f"*terminal:* {terminal.total_passed} passed, "
            f"{terminal.total_failed} failed"
        )

    if result.layers.api is not None:
        api = result.layers.api
        passed = sum(1 for check in api.checks if check.status == LayerStatus.PASSED)
        total = len(api.checks)
        lines.append(f"*api:* {passed}/{total} checks passed")

    if result.layers.ui is not None:
        ui = result.layers.ui
        scenario_count = len(ui.scenarios)
        step_count = len(ui.steps)
        lines.append(f"*ui:* {scenario_count} scenarios, {step_count} steps")

    if not lines:
        lines.append("_No layer results recorded_")
    return lines


def _select_upload_files(
    result: RunResult,
    artifact_dir: Path,
) -> list[tuple[Path, str]]:
    selected: list[tuple[Path, str]] = []
    seen: set[Path] = set()

    def add(path: Path, title: str) -> None:
        resolved = path.resolve()
        if resolved.is_file() and resolved not in seen:
            seen.add(resolved)
            selected.append((resolved, title))

    if result.artifacts.video:
        add(artifact_dir / result.artifacts.video, "Desktop recording")

    screenshots = result.artifacts.screenshots or []
    if screenshots:
        add(artifact_dir / screenshots[0], "First screenshot")
        if len(screenshots) > 1:
            add(artifact_dir / screenshots[-1], "Final screenshot")

    if result.layers.ui is not None and result.layers.ui.status == LayerStatus.FAILED:
        failed_step = next(
            (
                step
                for step in result.layers.ui.steps
                if step.status == LayerStatus.FAILED and step.screenshot
            ),
            None,
        )
        if failed_step is not None and failed_step.screenshot:
            add(artifact_dir / failed_step.screenshot, "Failure screenshot")

    return selected


def _report_path(result: RunResult, artifact_dir: Path) -> str:
    report_file = artifact_dir / REPORT_FILENAME
    if report_file.is_file():
        try:
            return str(report_file.relative_to(Path(result.repo).resolve()))
        except ValueError:
            pass
    output_parent = artifact_dir.parent.name
    return f".finalstrike/{output_parent}/{result.run_id}/{REPORT_FILENAME}"


def _total_duration_ms(result: RunResult) -> int:
    total = 0
    if result.layers.env is not None:
        total += result.layers.env.duration_ms
    if result.layers.build is not None:
        total += sum(command.duration_ms for command in result.layers.build.commands)
    if result.layers.terminal is not None:
        total += sum(command.duration_ms for command in result.layers.terminal.commands)
    if result.layers.api is not None:
        total += sum(check.duration_ms for check in result.layers.api.checks)
    return total


def _format_duration(duration_ms: int) -> str:
    seconds = max(duration_ms // 1000, 0)
    minutes, seconds = divmod(seconds, 60)
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def _safe_mrkdwn(value: str) -> str:
    return sanitize_response_body(value.replace("&", "&amp;"), {})


def _format_skipped_files(skipped_files: list[str]) -> str:
    lines = ["Skipped large attachments:"]
    lines.extend(f"• {item}" for item in skipped_files)
    return "\n".join(lines)


def _redact_error(message: str, secret_values: set[str]) -> str:
    redacted = message
    for value in secret_values:
        if value and len(value) >= 4:
            redacted = redacted.replace(value, "***")
    redacted = re.sub(
        r"(Bearer\s+)[A-Za-z0-9._~+/=-]+",
        r"\1***",
        redacted,
        flags=re.IGNORECASE,
    )
    redacted = re.sub(r"xox[baprs]-[A-Za-z0-9-]+", "***", redacted)
    return redacted
