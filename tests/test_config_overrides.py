"""Tests for gitignored local config overrides."""

from __future__ import annotations

import pytest

from finalstrike.config.loader import load_config, load_raw_config
from finalstrike.config.overrides import (
    ENV_LLM_BASE_URL,
    ENV_LLM_MODEL,
    apply_runtime_overlays,
    deep_merge_dict,
    merge_repo_config,
)
from finalstrike.config.context import load_repo_context
from tests.conftest import FIXTURE_REPO
from tests.support.cassette_repo import CASSETTE_SMOKE_REPO


def test_deep_merge_dict_nested() -> None:
    base = {"llm": {"base_url": "http://a", "model": "m1"}, "project": {"name": "x"}}
    overlay = {"llm": {"model": "m2"}}
    merged = deep_merge_dict(base, overlay)
    assert merged["llm"]["base_url"] == "http://a"
    assert merged["llm"]["model"] == "m2"
    assert merged["project"]["name"] == "x"


def test_local_yaml_overrides_committed_config(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_LLM_BASE_URL, raising=False)
    monkeypatch.delenv(ENV_LLM_MODEL, raising=False)
    (tmp_path / "finalstrike.yaml").write_text(
        """
version: "1"
project:
  name: demo
llm:
  provider: openai_compat
  base_url: http://localhost:11434/v1
  model: llama3
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "finalstrike.local.yaml").write_text(
        """
llm:
  base_url: https://api.example.com/v1
  model: gpt-4o
""".strip()
        + "\n",
        encoding="utf-8",
    )
    config = load_config(tmp_path)
    assert config.llm.base_url == "https://api.example.com/v1"
    assert config.llm.model == "gpt-4o"


def test_runtime_overrides_from_secrets_dict() -> None:
    raw = load_raw_config(FIXTURE_REPO)
    merged = apply_runtime_overlays(
        raw,
        secrets={
            ENV_LLM_BASE_URL: "https://api.example.com/v1",
            ENV_LLM_MODEL: "gpt-4o",
        },
    )
    assert merged["llm"]["base_url"] == "https://api.example.com/v1"
    assert merged["llm"]["model"] == "gpt-4o"


def test_runtime_overrides_precedence_over_local_yaml(tmp_path) -> None:
    (tmp_path / "finalstrike.yaml").write_text(
        """
version: "1"
project:
  name: demo
llm:
  provider: openai_compat
  base_url: http://localhost:11434/v1
  model: llama3
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "finalstrike.local.yaml").write_text(
        "llm:\n  model: from-local\n",
        encoding="utf-8",
    )
    config = load_config(
        tmp_path,
        secrets={ENV_LLM_MODEL: "from-secrets"},
    )
    assert config.llm.model == "from-secrets"


def test_committed_snapshot_repo_has_no_local_yaml_overlay() -> None:
    """Deterministic config lives under tests/fixtures/, not the mutable sample-app."""
    raw = load_raw_config(CASSETTE_SMOKE_REPO)
    merged, local_path = merge_repo_config(CASSETTE_SMOKE_REPO, raw)
    assert local_path is None
    assert merged["llm"]["base_url"] == "http://localhost:11434/v1"
    assert merged == raw


def test_load_repo_context_applies_local_yaml(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_LLM_BASE_URL, raising=False)
    monkeypatch.delenv(ENV_LLM_MODEL, raising=False)
    (tmp_path / "finalstrike.yaml").write_text(
        """
version: "1"
project:
  name: demo
llm:
  provider: openai_compat
  base_url: http://localhost:11434/v1
  model: llama3
secrets:
  file: .finalstrike/secrets.env
""".strip()
        + "\n",
        encoding="utf-8",
    )
    secrets_dir = tmp_path / ".finalstrike"
    secrets_dir.mkdir()
    (secrets_dir / "secrets.env").write_text("OPENAI_API_KEY=test-key\n", encoding="utf-8")
    (tmp_path / "finalstrike.local.yaml").write_text(
        "llm:\n  model: gpt-4o-mini\n",
        encoding="utf-8",
    )
    ctx = load_repo_context(tmp_path, inject_secrets=False)
    assert ctx.config.llm.model == "gpt-4o-mini"
