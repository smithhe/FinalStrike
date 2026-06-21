"""Structural assertions for VerificationPlan consistency."""

from __future__ import annotations

import re

from finalstrike.config.models import VerificationPlan
from finalstrike.fixture_capabilities import FixtureCapabilities


def extract_acceptance_bullets(content: str) -> list[str]:
    """Return markdown bullet lines from acceptance criteria."""
    bullets: list[str] = []
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            bullets.append(stripped[2:].strip())
    return bullets


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def _tokens(value: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9_/]+", value.lower()) if len(token) > 2}


def assert_plan_covers_acceptance(plan: VerificationPlan, acceptance: str) -> None:
    """Each acceptance bullet should map to at least one scenario."""
    bullets = extract_acceptance_bullets(acceptance)
    assert bullets, "acceptance criteria must contain bullet items"

    for bullet in bullets:
        bullet_norm = _normalize_text(bullet)
        bullet_tokens = _tokens(bullet)
        matched = False
        for scenario in plan.scenarios:
            source_norm = _normalize_text(scenario.source)
            if bullet_norm in source_norm or source_norm in bullet_norm:
                matched = True
                break
            if bullet_tokens and bullet_tokens.issubset(_tokens(source_norm)):
                matched = True
                break
        assert matched, f"No scenario maps to acceptance bullet: {bullet!r}"


def assert_plan_covers_capabilities(
    plan: VerificationPlan,
    capabilities: FixtureCapabilities,
) -> None:
    """Plan steps should cover implemented capabilities from capabilities.yaml."""
    for api_cap in capabilities.implemented.api:
        found = any(
            step.method.upper() == api_cap.method.upper() and step.path == api_cap.path
            for scenario in plan.scenarios
            for step in scenario.layers.api
        )
        assert found, (
            f"Plan missing API check {api_cap.method} {api_cap.path} "
            f"(expect {api_cap.expect_status})"
        )

    for terminal_cap in capabilities.implemented.terminal:
        found = any(
            terminal_cap.command in step.command
            for scenario in plan.scenarios
            for step in scenario.layers.terminal
        )
        assert found, f"Plan missing terminal command containing {terminal_cap.command!r}"

    for ui_cap in capabilities.implemented.ui:
        found = any(
            (
                ui_cap.route is not None
                and ui_cap.route in step.instruction
            )
            or (
                ui_cap.title is not None
                and ui_cap.title.lower() in step.instruction.lower()
            )
            for scenario in plan.scenarios
            for step in scenario.layers.ui
        )
        assert found, (
            f"Plan missing UI step for route={ui_cap.route!r} title={ui_cap.title!r}"
        )


def assert_plan_has_layer_coverage(plan: VerificationPlan) -> None:
    """Smoke plans should exercise terminal, api, and ui layers."""
    has_terminal = any(scenario.layers.terminal for scenario in plan.scenarios)
    has_api = any(scenario.layers.api for scenario in plan.scenarios)
    has_ui = any(scenario.layers.ui for scenario in plan.scenarios)
    assert has_terminal, "plan has no terminal layer steps"
    assert has_api, "plan has no api layer steps"
    assert has_ui, "plan has no ui layer steps"
