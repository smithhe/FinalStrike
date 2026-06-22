"""Tests for config models and validation."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from finalstrike.config.loader import load_config
from finalstrike.config.models import FinalStrikeConfig, RunResult, RunStatus, VerificationPlan


FIXTURE_REPO = Path(__file__).resolve().parents[1] / "fixtures" / "sample-app"


def test_load_sample_app_config() -> None:
    from tests.support.cassette_repo import CASSETTE_SMOKE_REPO

    config = load_config(CASSETTE_SMOKE_REPO)
    assert config.project.name == "sample-app"
    assert config.llm.provider.value == "openai_compat"
    assert config.api is not None
    assert config.api.health[0].path == "/health"


def test_finalstrike_config_requires_project() -> None:
    with pytest.raises(ValidationError):
        FinalStrikeConfig.model_validate({"version": "1", "llm": {"base_url": "x", "model": "y"}})


def test_verification_plan_minimal() -> None:
    plan = VerificationPlan.model_validate(
        {
            "scenarios": [
                {
                    "id": "ac-1",
                    "source": "User can open the Tasks page",
                    "layers": {
                        "terminal": [{"command": "pytest", "reason": "unit coverage"}],
                        "api": [
                            {
                                "method": "GET",
                                "path": "/api/tasks",
                                "expect": {"status": 200},
                            }
                        ],
                        "ui": [{"instruction": "Verify task list renders"}],
                    },
                }
            ],
            "gaps": [{"item": "OAuth login", "reason": "Not in AC"}],
        }
    )
    assert len(plan.scenarios) == 1
    assert plan.scenarios[0].layers.api[0].expect.status == 200


def test_run_result_minimal() -> None:
    result = RunResult.model_validate(
        {
            "run_id": "2026-06-20T14-30-00Z",
            "repo": "/path/to/target",
            "status": "passed",
        }
    )
    assert result.status == RunStatus.PASSED
    assert result.layers.env is None
    assert result.artifacts.video is None


def test_run_result_plan_shaped() -> None:
    result = RunResult.model_validate(
        {
            "run_id": "2026-06-20T14-30-00Z",
            "repo": "/path/to/target",
            "branch": "feature/my-change",
            "status": "partial",
            "layers": {
                "env": {"status": "passed", "duration_ms": 45000, "logs": "started"},
                "terminal": {
                    "status": "passed",
                    "commands": [
                        {
                            "name": "unit",
                            "status": "passed",
                            "exit_code": 0,
                            "duration_ms": 1200,
                            "total_passed": 138,
                            "total_failed": 0,
                        }
                    ],
                    "total_passed": 138,
                    "total_failed": 0,
                },
                "api": {
                    "status": "passed",
                    "checks": [
                        {
                            "method": "GET",
                            "path": "/health",
                            "status": "passed",
                            "expected_status": 200,
                            "actual_status": 200,
                            "duration_ms": 42,
                        }
                    ],
                },
                "ui": {
                    "status": "failed",
                    "scenarios": [{"id": "ac-1", "status": "failed", "steps_completed": 2}],
                    "steps": [
                        {
                            "step_index": 0,
                            "action": "open browser",
                            "screenshot": "step-001.png",
                            "status": "passed",
                        }
                    ],
                },
            },
            "artifacts": {
                "video": "runs/.../desktop.webm",
                "screenshots": ["step-001.png"],
                "html_report": "runs/.../report.html",
            },
            "gaps": [{"item": "OAuth login", "reason": "Not in AC"}],
        }
    )
    assert result.branch == "feature/my-change"
    assert result.layers.env is not None
    assert result.layers.env.duration_ms == 45000
    assert result.layers.terminal is not None
    assert result.layers.terminal.total_passed == 138
    assert result.layers.api is not None
    assert result.layers.api.checks[0].actual_status == 200
    assert result.layers.ui is not None
    assert result.layers.ui.steps[0].screenshot == "step-001.png"
    assert result.artifacts.html_report == "runs/.../report.html"
    assert len(result.gaps) == 1


def test_finalstrike_config_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        FinalStrikeConfig.model_validate(
            {
                "version": "1",
                "project": {"name": "x"},
                "llm": {
                    "provider": "openai_compat",
                    "base_url": "http://localhost",
                    "model": "m",
                    "api_key": "secret",
                },
            }
        )
