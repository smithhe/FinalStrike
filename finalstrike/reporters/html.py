"""HTML report generator (Phase 8)."""

from __future__ import annotations

import html
from datetime import datetime, timezone
from importlib.resources import files
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from finalstrike import __version__
from finalstrike.config.models import RunResult, RunStatus
from finalstrike.runners.api import sanitize_response_body

REPORT_FILENAME = "report.html"
_OUTPUT_LIMIT = 8192
_OUTPUT_TRUNCATION = "\n...[truncated]"

_STATUS_BADGES: dict[RunStatus, tuple[str, str]] = {
    RunStatus.PASSED: ("✅", "passed"),
    RunStatus.FAILED: ("❌", "failed"),
    RunStatus.PARTIAL: ("⚠️", "partial"),
}


def resolve_report_template() -> Path:
    """Locate the Jinja2 report template in development or installed package."""
    dev_path = Path(__file__).resolve().parents[2] / "templates" / REPORT_FILENAME.replace(
        ".html", ".html.j2"
    )
    if dev_path.is_file():
        return dev_path
    packaged = files("finalstrike").joinpath("templates/report.html.j2")
    return Path(str(packaged))


def render_html_report(
    result: RunResult,
    *,
    artifact_dir: Path,
    secrets: dict[str, str] | None = None,
    version: str | None = None,
) -> Path:
    """Render a self-contained HTML evidence report into ``artifact_dir``."""
    artifact_dir = artifact_dir.resolve()
    template_path = resolve_report_template()
    env = Environment(
        loader=FileSystemLoader(str(template_path.parent)),
        autoescape=select_autoescape(enabled_extensions=("html", "j2")),
    )
    template = env.get_template(template_path.name)
    context = _build_template_context(
        result,
        secrets=secrets or {},
        version=version or __version__,
    )
    output_path = artifact_dir / REPORT_FILENAME
    output_path.write_text(template.render(**context), encoding="utf-8")
    return output_path


def render_html_report_from_run_dir(
    run_dir: Path,
    *,
    secrets: dict[str, str] | None = None,
    version: str | None = None,
) -> Path:
    """Load ``result.json`` from a run directory and render ``report.html``."""
    run_dir = run_dir.resolve()
    result_path = run_dir / "result.json"
    if not result_path.is_file():
        raise FileNotFoundError(f"Missing run result: {result_path}")
    result = RunResult.model_validate_json(result_path.read_text(encoding="utf-8"))
    return render_html_report(
        result,
        artifact_dir=run_dir,
        secrets=secrets,
        version=version,
    )


def _build_template_context(
    result: RunResult,
    *,
    secrets: dict[str, str],
    version: str,
) -> dict[str, object]:
    badge, status_label = _STATUS_BADGES.get(result.status, ("❓", result.status.value))
    return {
        "badge": badge,
        "status_label": status_label,
        "status_class": result.status.value,
        "run_id": result.run_id,
        "repo": result.repo,
        "branch": result.branch,
        "version": version,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "total_duration_ms": _total_duration_ms(result),
        "layers": _layer_sections(result, secrets=secrets),
        "gaps": [
            {"item": _safe_text(gap.item), "reason": _safe_text(gap.reason)}
            for gap in result.gaps
        ],
        "artifacts": _artifact_section(result),
    }


def _layer_sections(result: RunResult, *, secrets: dict[str, str]) -> list[dict[str, object]]:
    sections: list[dict[str, object]] = []

    if result.layers.env is not None:
        env = result.layers.env
        sections.append(
            {
                "key": "env",
                "title": "Environment",
                "status": env.status.value,
                "duration_ms": env.duration_ms,
                "summary": f"Bootstrap {env.status.value} in {env.duration_ms}ms",
                "logs": _sanitize_output(env.logs, secrets),
            }
        )

    if result.layers.build is not None:
        build = result.layers.build
        sections.append(
            {
                "key": "build",
                "title": "Build",
                "status": build.status.value,
                "duration_ms": sum(command.duration_ms for command in build.commands),
                "commands": [
                    {
                        "name": _safe_text(command.name),
                        "status": command.status.value,
                        "exit_code": command.exit_code,
                        "duration_ms": command.duration_ms,
                        "stdout": _sanitize_output(command.stdout, secrets),
                        "stderr": _sanitize_output(command.stderr, secrets),
                    }
                    for command in build.commands
                ],
            }
        )

    if result.layers.terminal is not None:
        terminal = result.layers.terminal
        sections.append(
            {
                "key": "terminal",
                "title": "Terminal",
                "status": terminal.status.value,
                "duration_ms": sum(command.duration_ms for command in terminal.commands),
                "total_passed": terminal.total_passed,
                "total_failed": terminal.total_failed,
                "commands": [
                    {
                        "name": _safe_text(command.name),
                        "status": command.status.value,
                        "exit_code": command.exit_code,
                        "duration_ms": command.duration_ms,
                        "total_passed": command.total_passed,
                        "total_failed": command.total_failed,
                        "stdout": _sanitize_output(command.stdout, secrets),
                        "stderr": _sanitize_output(command.stderr, secrets),
                    }
                    for command in terminal.commands
                ],
            }
        )

    if result.layers.api is not None:
        api = result.layers.api
        sections.append(
            {
                "key": "api",
                "title": "API",
                "status": api.status.value,
                "duration_ms": sum(check.duration_ms for check in api.checks),
                "checks": [
                    {
                        "method": check.method,
                        "path": _safe_text(check.path),
                        "status": check.status.value,
                        "expected_status": check.expected_status,
                        "actual_status": check.actual_status,
                        "duration_ms": check.duration_ms,
                        "error": _safe_text(check.error) if check.error else None,
                        "response_body": _sanitize_output(check.response_body, secrets),
                    }
                    for check in api.checks
                ],
            }
        )

    if result.layers.ui is not None:
        ui = result.layers.ui
        failed_step = next(
            (step.step_index for step in ui.steps if step.status.value == "failed"),
            None,
        )
        sections.append(
            {
                "key": "ui",
                "title": "UI",
                "status": ui.status.value,
                "error": _safe_text(ui.error) if ui.error else None,
                "scenarios": [
                    {
                        "id": _safe_text(scenario.id),
                        "status": scenario.status.value,
                        "steps_completed": scenario.steps_completed,
                    }
                    for scenario in ui.scenarios
                ],
                "steps": [
                    {
                        "step_index": step.step_index,
                        "action": _safe_text(step.action),
                        "status": step.status.value,
                        "screenshot": step.screenshot,
                        "timestamp_ms": step.timestamp_ms,
                        "failed": step.step_index == failed_step,
                    }
                    for step in ui.steps
                ],
            }
        )

    return sections


def _artifact_section(result: RunResult) -> dict[str, object]:
    screenshots = result.artifacts.screenshots or []
    gallery: list[dict[str, object]] = []
    ui_steps = result.layers.ui.steps if result.layers.ui else []
    step_by_screenshot = {
        step.screenshot: step for step in ui_steps if step.screenshot
    }
    for index, screenshot in enumerate(screenshots, start=1):
        step = step_by_screenshot.get(screenshot)
        gallery.append(
            {
                "src": screenshot,
                "label": (
                    f"Step {step.step_index + 1}: {step.action}"
                    if step is not None
                    else f"Screenshot {index}"
                ),
                "failed": step is not None and step.status.value == "failed",
            }
        )
    video = result.artifacts.video
    video_mime = "video/mp4"
    if video and video.endswith(".webm"):
        video_mime = "video/webm"
    return {
        "video": video,
        "video_mime": video_mime,
        "screenshots": gallery,
    }


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


def _sanitize_output(text: str, secrets: dict[str, str]) -> str:
    if not text:
        return ""
    redacted = sanitize_response_body(text, secrets)
    if len(redacted) > _OUTPUT_LIMIT:
        keep = _OUTPUT_LIMIT - len(_OUTPUT_TRUNCATION)
        return redacted[:keep] + _OUTPUT_TRUNCATION
    return redacted


def _safe_text(value: str | None) -> str:
    if value is None:
        return ""
    return html.escape(value, quote=True)
