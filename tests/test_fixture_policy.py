"""Guardrails for test repo usage (see tests/README.md)."""

from __future__ import annotations

from pathlib import Path

import pytest

from finalstrike.config.overrides import LOCAL_CONFIG_FILENAME
from tests.conftest import CASSETTE_SMOKE_REPO, FIXTURE_REPO


def test_cassette_smoke_repo_has_no_local_yaml_overlay() -> None:
    local_path = CASSETTE_SMOKE_REPO / LOCAL_CONFIG_FILENAME
    assert not local_path.is_file(), (
        f"{LOCAL_CONFIG_FILENAME} must not be committed under {CASSETTE_SMOKE_REPO}; "
        "use fixtures/sample-app for developer overrides"
    )


@pytest.mark.parametrize(
    "path",
    [
        pytest.param(
            FIXTURE_REPO / "finalstrike.yaml",
            id="fixture-committed-yaml",
        ),
        pytest.param(
            CASSETTE_SMOKE_REPO / "finalstrike.yaml",
            id="cassette-committed-yaml",
        ),
    ],
)
def test_committed_finalstrike_yaml_exists(path: Path) -> None:
    assert path.is_file()
