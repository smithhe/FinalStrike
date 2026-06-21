"""Shared pytest fixtures and optional-integration markers."""

from __future__ import annotations

import shutil
import socket
from pathlib import Path

import httpx
import pytest

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_REPO = WORKSPACE_ROOT / "fixtures" / "sample-app"
ACCEPTANCE_SMOKE = FIXTURE_REPO / "acceptance-smoke.md"
ACCEPTANCE_FULL = FIXTURE_REPO / "acceptance-full.md"
# Default acceptance file for P0–P4 integration tests.
ACCEPTANCE_FILE = ACCEPTANCE_SMOKE


def _tcp_reachable(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def ollama_available() -> bool:
    try:
        with httpx.Client(timeout=1.0) as client:
            response = client.get("http://localhost:11434/v1/models")
            return response.status_code < 500
    except httpx.HTTPError:
        return False


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
        "requires_ollama: needs Ollama at http://localhost:11434 (P5 planner integration)",
    )
    config.addinivalue_line(
        "markers",
        "requires_platform_tools: needs ffmpeg and xdotool or ydotool (P6/P7)",
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    del config
    if not ollama_available():
        skip_ollama = pytest.mark.skip(
            reason="Ollama not reachable at http://localhost:11434"
        )
        for item in items:
            if "requires_ollama" in item.keywords:
                item.add_marker(skip_ollama)

    if not platform_tools_available():
        skip_platform = pytest.mark.skip(
            reason="ffmpeg and xdotool/ydotool not all available"
        )
        for item in items:
            if "requires_platform_tools" in item.keywords:
                item.add_marker(skip_platform)
