"""Tests for P5 LLM test planner."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from finalstrike.cli.main import app
from finalstrike.config.context import load_repo_context
from finalstrike.config.models import VerificationPlan
from finalstrike.planner.planner import (
    extract_json_object,
    generate_verification_plan,
    validate_plan_payload,
)
from finalstrike.planner.prompt import SYSTEM_PROMPT, build_planner_messages
from finalstrike.providers.openai_compat import (
    LLMProviderError,
    OpenAICompatProvider,
    resolve_api_key,
)
from tests.conftest import ACCEPTANCE_FILE, FIXTURE_REPO, live_llm_available

runner = CliRunner()

SMOKE_PLAN_JSON = {
    "scenarios": [
        {
            "id": "ac-1",
            "source": "API health endpoint returns 200 on GET /health",
            "layers": {
                "terminal": [],
                "api": [
                    {
                        "method": "GET",
                        "path": "/health",
                        "expect": {"status": 200},
                    }
                ],
                "ui": [],
            },
        },
        {
            "id": "ac-2",
            "source": 'Frontend landing page loads at / with title "Sample App"',
            "layers": {
                "terminal": [],
                "api": [],
                "ui": [
                    {
                        "instruction": (
                            "Open http://localhost:3000/ and verify the page "
                            'title is "Sample App"'
                        )
                    }
                ],
            },
        },
        {
            "id": "ac-3",
            "source": "Unit tests pass via `pytest -q`",
            "layers": {
                "terminal": [
                    {
                        "command": "pytest -q",
                        "reason": "Run unit tests from finalstrike.yaml",
                    }
                ],
                "api": [],
                "ui": [],
            },
        },
    ],
    "gaps": [],
}


class FakeLLM:
    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls = 0

    def chat_completion(
        self,
        messages,
        *,
        temperature: float = 0.2,
        json_mode: bool = True,
    ) -> str:
        del messages, temperature, json_mode
        if self.calls >= len(self._responses):
            raise RuntimeError("no more fake responses")
        response = self._responses[self.calls]
        self.calls += 1
        return response


def test_resolve_api_key_from_secrets() -> None:
    assert (
        resolve_api_key(
            {"OPENAI_API_KEY": "vault-key"},
            base_url="https://api.openai.com/v1",
        )
        == "vault-key"
    )


def test_resolve_api_key_local_placeholder(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert (
        resolve_api_key({}, base_url="http://localhost:11434/v1") == "ollama"
    )


def test_resolve_api_key_missing_remote(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(LLMProviderError, match="OPENAI_API_KEY"):
        resolve_api_key({}, base_url="https://api.openai.com/v1")


def test_extract_json_object_raw() -> None:
    payload = extract_json_object('{"scenarios": [], "gaps": []}')
    assert payload == {"scenarios": [], "gaps": []}


def test_extract_json_object_from_fence() -> None:
    text = 'Here is the plan:\n```json\n{"scenarios": [], "gaps": []}\n```'
    payload = extract_json_object(text)
    assert payload == {"scenarios": [], "gaps": []}


def test_validate_plan_payload_rejects_invalid() -> None:
    with pytest.raises(ValueError, match="Invalid VerificationPlan"):
        validate_plan_payload({"scenarios": "not-a-list", "gaps": []})


def test_build_planner_messages_includes_context() -> None:
    context = load_repo_context(
        FIXTURE_REPO,
        acceptance_path=ACCEPTANCE_FILE,
        inject_secrets=False,
    )
    messages = build_planner_messages(context)
    assert messages[0][0] == "system"
    assert SYSTEM_PROMPT in messages[0][1]
    user = messages[1][1]
    assert "sample-app" in user
    assert "smoke verification" in user
    assert "VerificationPlan JSON Schema" in user


def test_build_planner_messages_includes_validation_error() -> None:
    context = load_repo_context(
        FIXTURE_REPO,
        acceptance_path=ACCEPTANCE_FILE,
        inject_secrets=False,
    )
    messages = build_planner_messages(context, validation_error="missing scenarios")
    assert "missing scenarios" in messages[1][1]


def test_generate_verification_plan_success() -> None:
    context = load_repo_context(
        FIXTURE_REPO,
        acceptance_path=ACCEPTANCE_FILE,
        inject_secrets=False,
    )
    fake = FakeLLM([json.dumps(SMOKE_PLAN_JSON)])
    plan = generate_verification_plan(context, provider=fake)
    assert isinstance(plan, VerificationPlan)
    assert len(plan.scenarios) == 3
    assert fake.calls == 1
    assert any(
        step.command == "pytest -q"
        for s in plan.scenarios
        for step in s.layers.terminal
    )
    assert any(step.path == "/health" for s in plan.scenarios for step in s.layers.api)
    assert any(step.instruction for s in plan.scenarios for step in s.layers.ui)


def test_generate_verification_plan_retries_on_invalid_json() -> None:
    context = load_repo_context(
        FIXTURE_REPO,
        acceptance_path=ACCEPTANCE_FILE,
        inject_secrets=False,
    )
    fake = FakeLLM(
        [
            "not json",
            json.dumps(SMOKE_PLAN_JSON),
        ]
    )
    plan = generate_verification_plan(context, provider=fake, max_retries=3)
    assert len(plan.scenarios) == 3
    assert fake.calls == 2


def test_generate_verification_plan_requires_acceptance() -> None:
    context = load_repo_context(FIXTURE_REPO, inject_secrets=False)
    with pytest.raises(ValueError, match="Acceptance criteria"):
        generate_verification_plan(context, provider=FakeLLM([]))


def test_plan_cli_no_dry_run_with_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_generate(context, **kwargs):
        del kwargs
        return VerificationPlan.model_validate(SMOKE_PLAN_JSON)

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
    payload = json.loads(result.stdout)
    assert len(payload["scenarios"]) == 3
    assert "LLM planner is not implemented" not in result.stderr


def test_plan_cli_no_dry_run_planner_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fail(context, **kwargs):
        del context, kwargs
        raise ValueError("bad plan")

    monkeypatch.setattr(
        "finalstrike.cli.main.generate_verification_plan",
        _fail,
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
    assert result.exit_code == 1
    assert "Planner error" in result.stderr


def test_openai_compat_provider_from_context(tmp_path: Path) -> None:
    (tmp_path / "finalstrike.yaml").write_text(
        """
version: "1"
project:
  name: provider-test
llm:
  provider: openai_compat
  base_url: http://localhost:11434/v1
  model: unit-test-model
secrets:
  file: .finalstrike/secrets.env
""".strip()
        + "\n",
        encoding="utf-8",
    )
    secrets_dir = tmp_path / ".finalstrike"
    secrets_dir.mkdir()
    (secrets_dir / "secrets.env").write_text("OPENAI_API_KEY=test-key\n", encoding="utf-8")

    context = load_repo_context(tmp_path, inject_secrets=False)
    provider = OpenAICompatProvider.from_context(
        context.config.llm,
        context.secrets,
    )
    assert provider.config.model == context.config.llm.model == "unit-test-model"


@pytest.mark.requires_live_llm
def test_live_llm_marker_skips_when_unavailable() -> None:
    """Placeholder for live planner tests; skipped unless configured LLM is reachable."""
    assert live_llm_available()
