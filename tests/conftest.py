"""Shared pytest fixtures and optional-integration markers."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from finalstrike.providers.live import assess_live_llm

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_REPO = WORKSPACE_ROOT / "fixtures" / "sample-app"
# Committed config snapshot for deterministic tests (no gitignored local.yaml).
CASSETTE_SMOKE_REPO = WORKSPACE_ROOT / "tests" / "fixtures" / "cassette-smoke-v1"
ACCEPTANCE_SMOKE = FIXTURE_REPO / "acceptance-smoke.md"
ACCEPTANCE_FULL = FIXTURE_REPO / "acceptance-full.md"
# Default acceptance file for P0–P4 integration tests.
ACCEPTANCE_FILE = ACCEPTANCE_SMOKE


def live_llm_available(repo: Path | None = None) -> bool:
    target = repo or FIXTURE_REPO
    return assess_live_llm(target).ready


def live_llm_skip_reason(repo: Path | None = None) -> str:
    target = repo or FIXTURE_REPO
    return assess_live_llm(target).detail


def platform_tools_available() -> bool:
    return shutil.which("ffmpeg") is not None and (
        shutil.which("xdotool") is not None or shutil.which("ydotool") is not None
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "llm_cassette: replay committed LLM recordings (deterministic CI)",
    )
    config.addinivalue_line(
        "markers",
        "requires_live_llm: needs configured llm.base_url reachable (P5 planner)",
    )
    config.addinivalue_line(
        "markers",
        "requires_platform_tools: needs ffmpeg and xdotool or ydotool (P6/P7)",
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    del config
    llm_status = assess_live_llm(FIXTURE_REPO)
    if not llm_status.ready:
        skip_live = pytest.mark.skip(
            reason=f"Live LLM not available: {llm_status.detail}"
        )
        for item in items:
            if "requires_live_llm" in item.keywords:
                item.add_marker(skip_live)

    if not platform_tools_available():
        skip_platform = pytest.mark.skip(
            reason="ffmpeg and xdotool/ydotool not all available"
        )
        for item in items:
            if "requires_platform_tools" in item.keywords:
                item.add_marker(skip_platform)
