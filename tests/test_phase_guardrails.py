"""Guardrail tests that keep phase gaps visible."""

from __future__ import annotations

import pytest
import yaml
from typer.testing import CliRunner

from finalstrike.cli.main import app
from finalstrike.fixture_capabilities import load_capabilities
from finalstrike.phase_status import IMPLEMENTED_PHASES, STUB_MODULES, next_unimplemented_phases
from tests.conftest import (
    ACCEPTANCE_FULL,
    ACCEPTANCE_SMOKE,
    FIXTURE_REPO,
    live_llm_available,
)

runner = CliRunner()


def test_implemented_phases_cover_p0_through_p6() -> None:
    assert IMPLEMENTED_PHASES == frozenset({0, 1, 2, 3, 4, 5, 6})
    assert next_unimplemented_phases()[0] == 7


def test_stub_modules_reference_future_phases() -> None:
    phases = {item.phase for item in STUB_MODULES}
    assert phases >= {7, 8, 9, 10}


def test_capabilities_manifest_present() -> None:
    capabilities = load_capabilities(FIXTURE_REPO / "capabilities.yaml")
    assert capabilities.version == "1"
    assert capabilities.implemented.api
    assert capabilities.planned.api


def test_smoke_acceptance_matches_implemented_api() -> None:
    capabilities = load_capabilities(FIXTURE_REPO / "capabilities.yaml")
    smoke = ACCEPTANCE_SMOKE.read_text(encoding="utf-8")
    for check in capabilities.implemented.api:
        assert check.path in smoke
        assert str(check.expect_status) in smoke


def test_full_acceptance_documents_planned_work() -> None:
    full = ACCEPTANCE_FULL.read_text(encoding="utf-8")
    assert "Fixture status" in full
    assert "capabilities.yaml" in full
    assert "POST /api/tasks" in full


def test_doctor_cli_fixture_repo() -> None:
    result = runner.invoke(
        app,
        ["doctor", "--repo", str(FIXTURE_REPO)],
    )
    assert result.exit_code == 0
    assert "Fixture planned work" in result.output


def test_capabilities_planned_not_duplicated_in_implemented() -> None:
    capabilities = load_capabilities(FIXTURE_REPO / "capabilities.yaml")
    implemented_paths = {item.path for item in capabilities.implemented.api}
    planned_paths = {item.path for item in capabilities.planned.api}
    assert implemented_paths.isdisjoint(planned_paths)


def test_smoke_planner_cassette_present() -> None:
    from tests.support.llm_cassette import DEFAULT_SMOKE_CASSETTE_ID, load_planner_cassette

    cassette = load_planner_cassette(DEFAULT_SMOKE_CASSETTE_ID)
    assert cassette.meta.component == "planner"
    assert cassette.responses
    assert cassette.canonical_plan["scenarios"]


def test_smoke_action_cassette_present() -> None:
    from tests.support.action_cassette import (
        DEFAULT_SMOKE_TITLE_CASSETTE_ID,
        load_action_cassette,
    )

    cassette = load_action_cassette(DEFAULT_SMOKE_TITLE_CASSETTE_ID)
    assert cassette.meta.component == "computer_use"
    assert cassette.responses


@pytest.mark.requires_live_llm
def test_live_llm_marker_skips_when_unavailable() -> None:
    """Placeholder for P5 integration tests; skipped unless configured LLM is reachable."""
    assert live_llm_available()
