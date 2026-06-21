"""Tests for validate-config CLI."""

from __future__ import annotations

from pathlib import Path

import yaml
from typer.testing import CliRunner

from finalstrike.cli.main import app

FIXTURE_REPO = Path(__file__).resolve().parents[1] / "fixtures" / "sample-app"
runner = CliRunner()


def test_validate_config_success_on_sample_app() -> None:
    result = runner.invoke(app, ["validate-config", "--repo", str(FIXTURE_REPO)])
    assert result.exit_code == 0
    assert "Configuration valid" in result.stderr
    assert "sample-app" in result.stderr


def test_validate_config_missing_finalstrike_yaml(tmp_path: Path) -> None:
    result = runner.invoke(app, ["validate-config", "--repo", str(tmp_path)])
    assert result.exit_code == 1
    assert "No finalstrike.yaml found" in result.stderr


def test_validate_config_bad_yaml(tmp_path: Path) -> None:
    config_path = tmp_path / "finalstrike.yaml"
    config_path.write_text("version: [unclosed\n", encoding="utf-8")
    result = runner.invoke(app, ["validate-config", "--repo", str(tmp_path)])
    assert result.exit_code == 1
    assert "YAML parse error" in result.stderr


def test_validate_config_invalid_provider(tmp_path: Path) -> None:
    config = {
        "version": "1",
        "project": {"name": "bad-app"},
        "llm": {
            "provider": "unknown_provider",
            "base_url": "http://localhost",
            "model": "m",
        },
    }
    (tmp_path / "finalstrike.yaml").write_text(
        yaml.safe_dump(config), encoding="utf-8"
    )
    result = runner.invoke(app, ["validate-config", "--repo", str(tmp_path)])
    assert result.exit_code == 1
    assert "Configuration validation failed" in result.stderr


def test_validate_config_rejects_extra_llm_fields(tmp_path: Path) -> None:
    config = {
        "version": "1",
        "project": {"name": "bad-app"},
        "llm": {
            "provider": "openai_compat",
            "base_url": "http://localhost",
            "model": "m",
            "api_key": "secret",
        },
    }
    (tmp_path / "finalstrike.yaml").write_text(
        yaml.safe_dump(config), encoding="utf-8"
    )
    result = runner.invoke(app, ["validate-config", "--repo", str(tmp_path)])
    assert result.exit_code == 1
    assert "Configuration validation failed" in result.stderr
    assert "api_key" in result.stderr


def test_validate_config_nonexistent_repo() -> None:
    result = runner.invoke(app, ["validate-config", "--repo", "/nonexistent"])
    assert result.exit_code == 1
    assert "Repo path does not exist" in result.stderr
