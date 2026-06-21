"""Tests for P1 config and context loading."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from finalstrike.cli.main import app
from finalstrike.config.acceptance import load_acceptance
from finalstrike.config.agents import load_agents
from finalstrike.config.context import load_repo_context
from finalstrike.config.environment import load_environment
from finalstrike.config.secrets import (
    apply_to_environ,
    load_secrets,
    parse_secrets_content,
    redact_secrets,
)

from tests.conftest import ACCEPTANCE_FILE, ACCEPTANCE_FULL, ACCEPTANCE_SMOKE, FIXTURE_REPO
runner = CliRunner()


# --- AGENTS.md ---


def test_load_agents_present_on_sample_app() -> None:
    agents = load_agents(FIXTURE_REPO)
    assert agents.present is True
    assert agents.path is not None
    assert agents.path.name == "AGENTS.md"
    assert "Sample App" in agents.content
    block = agents.to_context_block()
    assert "## AGENTS.md" in block
    assert "Smoke routes" in block


def test_load_agents_absent(tmp_path: Path) -> None:
    agents = load_agents(tmp_path)
    assert agents.present is False
    assert agents.content == ""
    assert agents.to_context_block() == ""


def test_agents_context_block_empty_when_blank_content(tmp_path: Path) -> None:
    agents_path = tmp_path / "AGENTS.md"
    agents_path.write_text("   \n", encoding="utf-8")
    agents = load_agents(tmp_path)
    assert agents.present is True
    assert agents.to_context_block() == ""


# --- environment.json ---


def test_load_environment_sample_app() -> None:
    env = load_environment(FIXTURE_REPO)
    assert env.present is True
    assert env.install == "pip install -r requirements.txt"
    assert len(env.terminals) == 2
    assert env.terminals[0].name == "api"
    assert env.terminals[0].command == "python3 -m sample_app.server"
    assert env.terminals[1].name == "frontend"
    summary = env.summary_lines()
    assert any("install:" in line for line in summary)
    assert any("api:" in line for line in summary)


def test_load_environment_missing(tmp_path: Path) -> None:
    env = load_environment(tmp_path)
    assert env.present is False
    assert env.terminals == []
    assert env.summary_lines() == ["(not present)"]


def test_load_environment_with_start(tmp_path: Path) -> None:
    cursor_dir = tmp_path / ".cursor"
    cursor_dir.mkdir()
    data = {
        "install": "npm install",
        "start": "npm run dev",
        "terminals": [{"name": "web", "command": "npm start"}],
    }
    (cursor_dir / "environment.json").write_text(
        json.dumps(data), encoding="utf-8"
    )
    env = load_environment(tmp_path)
    assert env.start == "npm run dev"
    assert len(env.terminals) == 1


def test_load_environment_invalid_terminals(tmp_path: Path) -> None:
    cursor_dir = tmp_path / ".cursor"
    cursor_dir.mkdir()
    (cursor_dir / "environment.json").write_text(
        json.dumps({"terminals": [{"name": "x"}]}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="terminals\\[0\\] invalid"):
        load_environment(tmp_path)


def test_load_environment_ignores_unknown_top_level_keys(tmp_path: Path) -> None:
    cursor_dir = tmp_path / ".cursor"
    cursor_dir.mkdir()
    data = {
        "install": "echo hi",
        "future_cursor_field": {"nested": True},
        "terminals": [],
    }
    (cursor_dir / "environment.json").write_text(
        json.dumps(data), encoding="utf-8"
    )
    env = load_environment(tmp_path)
    assert env.install == "echo hi"


# --- secrets ---


def test_parse_secrets_content_skips_comments_and_blanks() -> None:
    content = """
# comment line
OPENAI_API_KEY=secret123

BLANK_AFTER_EQUALS=

QUOTED="value"
SINGLE='other'
"""
    secrets = parse_secrets_content(content)
    assert secrets["OPENAI_API_KEY"] == "secret123"
    assert secrets["BLANK_AFTER_EQUALS"] == ""
    assert secrets["QUOTED"] == "value"
    assert secrets["SINGLE"] == "other"
    assert "comment" not in secrets


def test_parse_secrets_content_handles_export_prefix() -> None:
    secrets = parse_secrets_content("export OPENAI_API_KEY=secret123\n")
    assert secrets["OPENAI_API_KEY"] == "secret123"


def test_load_secrets_from_sample_app() -> None:
    secrets, warnings = load_secrets(FIXTURE_REPO, ".finalstrike/secrets.env")
    assert warnings == []
    assert "OPENAI_API_KEY" in secrets
    assert secrets["OPENAI_API_KEY"] == "fixture-test-key-not-real"
    assert "SLACK_BOT_TOKEN" in secrets


def test_load_secrets_missing_file(tmp_path: Path) -> None:
    secrets, warnings = load_secrets(tmp_path, ".finalstrike/secrets.env")
    assert secrets == {}
    assert len(warnings) == 1
    assert "not found" in warnings[0].lower()


def test_redact_secrets() -> None:
    redacted = redact_secrets({"KEY": "value", "OTHER": "x"})
    assert redacted == {"KEY": "***", "OTHER": "***"}


def test_apply_to_environ_merges_without_mutating_os_environ() -> None:
    base = {"EXISTING": "1"}
    secrets = {"NEW": "2"}
    merged = apply_to_environ(secrets, base=base)
    assert merged["EXISTING"] == "1"
    assert merged["NEW"] == "2"
    assert "NEW" not in os.environ or os.environ.get("NEW") != "2"


# --- acceptance ---


def test_load_acceptance_from_file() -> None:
    ac = load_acceptance(ACCEPTANCE_SMOKE)
    assert "smoke verification" in ac.content
    assert ac.source.endswith("acceptance-smoke.md")


def test_load_acceptance_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_acceptance(tmp_path / "missing.md")


def test_load_acceptance_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "empty.md"
    path.write_text("   \n", encoding="utf-8")
    with pytest.raises(ValueError, match="empty"):
        load_acceptance(path)


def test_load_acceptance_from_stdin_via_context(tmp_path: Path) -> None:
    _write_minimal_repo(tmp_path)
    ctx = load_repo_context(
        tmp_path,
        acceptance_stdin=True,
        acceptance_content="## AC\n- item one\n",
    )
    assert ctx.acceptance is not None
    assert ctx.acceptance.source == "stdin"
    assert "item one" in ctx.acceptance.content


# --- merged repo context ---


def test_load_repo_context_sample_app() -> None:
    ctx = load_repo_context(FIXTURE_REPO, acceptance_path=ACCEPTANCE_FILE)
    assert ctx.config.project.name == "sample-app"
    assert ctx.agents.present is True
    assert ctx.environment.present is True
    assert "OPENAI_API_KEY" in ctx.secrets
    assert ctx.acceptance is not None
    assert "smoke verification" in ctx.acceptance.content


def test_load_repo_context_full_acceptance() -> None:
    ctx = load_repo_context(FIXTURE_REPO, acceptance_path=ACCEPTANCE_FULL)
    assert ctx.acceptance is not None
    assert "Task list" in ctx.acceptance.content


def test_load_repo_context_injects_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    ctx = load_repo_context(
        FIXTURE_REPO,
        acceptance_path=ACCEPTANCE_FILE,
        inject_secrets=True,
    )
    assert "OPENAI_API_KEY" in ctx.subprocess_env
    assert os.environ.get("OPENAI_API_KEY") == ctx.secrets["OPENAI_API_KEY"]


def test_load_repo_context_skips_injection_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    ctx = load_repo_context(
        FIXTURE_REPO,
        acceptance_path=ACCEPTANCE_FILE,
        inject_secrets=False,
    )
    assert "OPENAI_API_KEY" in ctx.subprocess_env
    assert os.environ.get("OPENAI_API_KEY") is None


def test_planner_context_block_uses_agents_context_block() -> None:
    ctx = load_repo_context(FIXTURE_REPO, acceptance_path=ACCEPTANCE_FILE)
    block = ctx.planner_context_block()
    assert ctx.agents.to_context_block().strip() in block
    assert "Acceptance Criteria" in block
    assert "smoke verification" in block


def test_repo_context_redacts_secrets_in_dry_run() -> None:
    ctx = load_repo_context(FIXTURE_REPO, acceptance_path=ACCEPTANCE_FILE)
    output = ctx.format_dry_run()
    assert "fixture-test-key-not-real" not in output
    assert "fixture-slack-token" not in output
    assert "OPENAI_API_KEY: ***" in output
    assert "sample-app" in output
    assert "smoke verification" in output
    assert "Planner Context" in output
    assert ctx.agents.to_context_block().strip() in output
    assert "pip install -r requirements.txt" in output


def test_load_environment_invalid_json(tmp_path: Path) -> None:
    cursor_dir = tmp_path / ".cursor"
    cursor_dir.mkdir()
    (cursor_dir / "environment.json").write_text("not json", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid JSON"):
        load_environment(tmp_path)


# --- CLI plan ---


def test_plan_dry_run_sample_app() -> None:
    result = runner.invoke(
        app,
        [
            "plan",
            "--repo",
            str(FIXTURE_REPO),
            "--acceptance",
            str(ACCEPTANCE_FILE),
            "--dry-run",
        ],
    )
    assert result.exit_code == 0
    assert "FinalStrike Plan Context" in result.stdout
    assert "sample-app" in result.stdout
    assert "smoke verification" in result.stdout
    assert "fixture-test-key-not-real" not in result.stdout
    assert "OPENAI_API_KEY: ***" in result.stdout


def test_plan_acceptance_stdin_empty() -> None:
    result = runner.invoke(
        app,
        ["plan", "--repo", str(FIXTURE_REPO), "--acceptance-stdin", "--dry-run"],
        input="",
    )
    assert result.exit_code == 1
    assert "empty" in result.stderr.lower()


def test_plan_acceptance_stdin() -> None:
    ac_text = "## Feature\n- criterion A\n"
    result = runner.invoke(
        app,
        ["plan", "--repo", str(FIXTURE_REPO), "--acceptance-stdin", "--dry-run"],
        input=ac_text,
    )
    assert result.exit_code == 0
    assert "criterion A" in result.stdout
    assert "stdin" in result.stdout


def test_plan_requires_acceptance_source() -> None:
    result = runner.invoke(
        app, ["plan", "--repo", str(FIXTURE_REPO), "--dry-run"]
    )
    assert result.exit_code == 1
    assert "Provide --acceptance" in result.stderr


def test_plan_rejects_both_acceptance_sources() -> None:
    result = runner.invoke(
        app,
        [
            "plan",
            "--repo",
            str(FIXTURE_REPO),
            "--acceptance",
            str(ACCEPTANCE_FILE),
            "--acceptance-stdin",
            "--dry-run",
        ],
    )
    assert result.exit_code == 1
    assert "only one" in result.stderr.lower()


def test_plan_missing_acceptance_file(tmp_path: Path) -> None:
    _write_minimal_repo(tmp_path)
    result = runner.invoke(
        app,
        [
            "plan",
            "--repo",
            str(tmp_path),
            "--acceptance",
            str(tmp_path / "nope.md"),
            "--dry-run",
        ],
    )
    assert result.exit_code == 1
    assert "not found" in result.stderr.lower()


def test_plan_no_dry_run_invokes_planner(monkeypatch: pytest.MonkeyPatch) -> None:
    from finalstrike.config.models import VerificationPlan

    def _fake_generate(context, **kwargs):
        del context, kwargs
        return VerificationPlan.model_validate(
            {"scenarios": [], "gaps": [{"item": "x", "reason": "y"}]}
        )

    monkeypatch.setattr(
        "finalstrike.cli.main.generate_verification_plan",
        _fake_generate,
    )
    result = runner.invoke(
        app,
        [
            "plan",
            "--repo",
            str(FIXTURE_REPO),
            "--acceptance",
            str(ACCEPTANCE_FILE),
            "--no-dry-run",
        ],
    )
    assert result.exit_code == 0
    assert '"scenarios"' in result.stdout
    assert "Gap analysis" in result.stderr


# --- helpers ---


def _write_minimal_repo(tmp_path: Path) -> None:
    config = {
        "version": "1",
        "project": {"name": "tmp"},
        "llm": {
            "provider": "openai_compat",
            "base_url": "http://localhost",
            "model": "m",
        },
    }
    (tmp_path / "finalstrike.yaml").write_text(
        yaml.safe_dump(config), encoding="utf-8"
    )
