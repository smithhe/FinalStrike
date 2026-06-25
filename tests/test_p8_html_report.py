"""Tests for P8 HTML report generator."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from finalstrike.cli.main import app
from finalstrike.config.models import (
    APICheckResult,
    APILayerResult,
    LayerStatus,
    RunResult,
    RunStatus,
)
from finalstrike.reporters.html import render_html_report, render_html_report_from_run_dir

from tests.conftest import FIXTURE_REPO

FIXTURE_RUN = Path(__file__).resolve().parent / "fixtures" / "run-result-sample"
runner = CliRunner()


def _load_fixture_result() -> RunResult:
    return RunResult.model_validate_json(
        (FIXTURE_RUN / "result.json").read_text(encoding="utf-8")
    )


def test_render_html_report_writes_self_contained_file(tmp_path: Path) -> None:
    result = _load_fixture_result()
    screenshot_src = FIXTURE_RUN / "screenshots" / "step-001.png"
    (tmp_path / "screenshots").mkdir()
    (tmp_path / "screenshots" / "step-001.png").write_bytes(screenshot_src.read_bytes())

    report_path = render_html_report(result, artifact_dir=tmp_path)

    assert report_path.name == "report.html"
    html = report_path.read_text(encoding="utf-8")
    assert "FinalStrike Evidence Report" in html
    assert "2026-06-20T14-30-00Z" in html
    assert "Gap report" in html
    assert "OAuth login" in html
    assert 'class="badge partial"' in html
    assert "138 passed" in html or "138</strong> passed" in html
    assert 'src="screenshots/step-001.png"' in html
    assert '<video controls' in html
    assert 'src="desktop.webm"' in html
    assert "open browser to tasks page" in html


def test_render_html_report_redacts_secrets(tmp_path: Path) -> None:
    result = RunResult(
        run_id="secret-run",
        repo="/tmp/repo",
        status=RunStatus.PASSED,
        layers={
            "api": APILayerResult(
                status=LayerStatus.PASSED,
                checks=[
                    APICheckResult(
                        method="GET",
                        path="/health",
                        status=LayerStatus.PASSED,
                        response_body='{"token":"super-secret-token-value"}',
                    )
                ],
            )
        },
    )
    report_path = render_html_report(
        result,
        artifact_dir=tmp_path,
        secrets={"API_TOKEN": "super-secret-token-value"},
    )
    html = report_path.read_text(encoding="utf-8")
    assert "super-secret-token-value" not in html
    assert "***" in html


def test_render_html_report_from_run_dir(tmp_path: Path) -> None:
    run_dir = tmp_path / "2026-06-20T14-30-00Z"
    run_dir.mkdir()
    (run_dir / "result.json").write_text(
        (FIXTURE_RUN / "result.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    report_path = render_html_report_from_run_dir(run_dir)
    assert report_path.is_file()
    assert "FinalStrike Evidence Report" in report_path.read_text(encoding="utf-8")


def test_report_cli_renders_fixture_run(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "finalstrike.yaml").write_text(
        (FIXTURE_REPO / "finalstrike.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (repo / ".finalstrike").mkdir()
    (repo / ".finalstrike" / "secrets.env").write_text(
        "OPENAI_API_KEY=fixture-test-key-not-real\n",
        encoding="utf-8",
    )
    run_dir = repo / ".finalstrike" / "runs" / "2026-06-20T14-30-00Z"
    run_dir.mkdir(parents=True)
    (run_dir / "result.json").write_text(
        (FIXTURE_RUN / "result.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "report",
            "--repo",
            str(repo),
            "--run-id",
            "2026-06-20T14-30-00Z",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "HTML report written" in result.output
    report = run_dir / "report.html"
    assert report.is_file()
    html = report.read_text(encoding="utf-8")
    assert "Gap report" in html
