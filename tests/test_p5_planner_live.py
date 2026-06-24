"""Optional live LLM planner tests — structural consistency, not golden equality."""

from __future__ import annotations

import pytest

from finalstrike.config.context import load_repo_context
from finalstrike.fixture_capabilities import load_capabilities
from finalstrike.planner.planner import generate_verification_plan
from tests.conftest import (
    ACCEPTANCE_FILE,
    ACCEPTANCE_FULL,
    ACCEPTANCE_SMOKE,
    FIXTURE_REPO,
    live_llm_available,
    live_llm_skip_reason,
)
from tests.support.cassette_repo import (
    CASSETTE_ACCEPTANCE_FULL,
    CASSETTE_ACCEPTANCE_SMOKE,
    CASSETTE_FULL_REPO,
    CASSETTE_SMOKE_REPO,
    load_cassette_full_context,
    load_cassette_smoke_context,
)
from tests.support.llm_cassette import (
    DEFAULT_FULL_CASSETTE_ID,
    DEFAULT_SMOKE_CASSETTE_ID,
    ReplayCassetteProvider,
    assert_cassette_matches_context,
    record_planner_cassette,
    should_record_llm,
)
from tests.support.plan_assertions import (
    assert_plan_covers_acceptance,
    assert_plan_covers_capabilities,
    assert_plan_has_layer_coverage,
    filter_capabilities_for_acceptance,
)


@pytest.mark.requires_live_llm
def test_generate_verification_plan_live_structural() -> None:
    """Exercise the developer's configured fixtures/sample-app LLM settings."""
    if not live_llm_available():
        pytest.skip(live_llm_skip_reason())

    context = load_repo_context(
        FIXTURE_REPO,
        acceptance_path=ACCEPTANCE_FILE,
        inject_secrets=True,
    )
    plan = generate_verification_plan(context, max_retries=2)
    capabilities = load_capabilities(FIXTURE_REPO / "capabilities.yaml")
    acceptance_text = ACCEPTANCE_SMOKE.read_text(encoding="utf-8")
    smoke_capabilities = filter_capabilities_for_acceptance(capabilities, acceptance_text)

    assert plan.scenarios
    assert_plan_has_layer_coverage(plan)
    assert_plan_covers_acceptance(plan, acceptance_text)
    assert_plan_covers_capabilities(plan, smoke_capabilities)


@pytest.mark.requires_live_llm
def test_generate_verification_plan_live_full_structural() -> None:
    """Exercise live planner against acceptance-full.md (Tiers 1–5 fixture)."""
    if not live_llm_available():
        pytest.skip(live_llm_skip_reason())

    context = load_repo_context(
        FIXTURE_REPO,
        acceptance_path=ACCEPTANCE_FULL,
        inject_secrets=True,
    )
    plan = generate_verification_plan(context, max_retries=2)
    capabilities = load_capabilities(FIXTURE_REPO / "capabilities.yaml")
    acceptance_text = ACCEPTANCE_FULL.read_text(encoding="utf-8")

    assert plan.scenarios
    assert_plan_has_layer_coverage(plan)
    assert_plan_covers_acceptance(plan, acceptance_text)
    assert_plan_covers_capabilities(plan, capabilities)


@pytest.mark.requires_live_llm
def test_record_smoke_planner_cassette() -> None:
    """Re-record smoke-v1 cassette when FINALSTRIKE_RECORD_LLM=1."""
    if not should_record_llm():
        pytest.skip("Set FINALSTRIKE_RECORD_LLM=1 to refresh cassettes")
    if not live_llm_available(CASSETTE_SMOKE_REPO):
        pytest.skip(live_llm_skip_reason(CASSETTE_SMOKE_REPO))

    context = load_cassette_smoke_context(inject_secrets=True)
    cassette = record_planner_cassette(
        DEFAULT_SMOKE_CASSETTE_ID,
        context,
        acceptance_path=CASSETTE_ACCEPTANCE_SMOKE,
        notes="Recorded via test_record_smoke_planner_cassette",
    )
    assert_cassette_matches_context(
        cassette,
        context,
        acceptance_path=CASSETTE_ACCEPTANCE_SMOKE,
    )

    replayed = generate_verification_plan(
        context,
        provider=ReplayCassetteProvider(cassette.responses),
    )
    assert replayed.model_dump(mode="json") == cassette.canonical_plan


@pytest.mark.requires_live_llm
def test_record_full_planner_cassette() -> None:
    """Re-record full-v1 cassette when FINALSTRIKE_RECORD_LLM=1."""
    if not should_record_llm():
        pytest.skip("Set FINALSTRIKE_RECORD_LLM=1 to refresh cassettes")
    if not live_llm_available(CASSETTE_FULL_REPO):
        pytest.skip(live_llm_skip_reason(CASSETTE_FULL_REPO))

    context = load_cassette_full_context(inject_secrets=True)
    cassette = record_planner_cassette(
        DEFAULT_FULL_CASSETTE_ID,
        context,
        acceptance_path=CASSETTE_ACCEPTANCE_FULL,
        notes="Recorded via test_record_full_planner_cassette",
    )
    assert_cassette_matches_context(
        cassette,
        context,
        acceptance_path=CASSETTE_ACCEPTANCE_FULL,
    )

    replayed = generate_verification_plan(
        context,
        provider=ReplayCassetteProvider(cassette.responses),
    )
    assert replayed.model_dump(mode="json") == cassette.canonical_plan
