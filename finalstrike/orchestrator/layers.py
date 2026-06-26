"""Per-layer dispatch helpers for the run orchestrator."""

from __future__ import annotations

from finalstrike.computer_use.config import resolve_computer_use_llm
from finalstrike.computer_use.loop import ActionLLMProvider, ActionLoop
from finalstrike.config.context import RepoContext
from finalstrike.config.models import (
    LayerStatus,
    UILayerResult,
    UIScenarioResult,
    VerificationPlan,
)
from finalstrike.evidence.session import EvidenceSession
from finalstrike.providers.openai_compat import OpenAICompatProvider


def run_ui_layer(
    context: RepoContext,
    plan: VerificationPlan,
    session: EvidenceSession,
    *,
    provider: ActionLLMProvider | None = None,
) -> UILayerResult:
    """Execute all UI instructions from ``plan`` and register screenshot evidence."""
    if context.config.ui is None:
        raise ValueError("finalstrike.yaml must define a ui: block for computer-use")

    ui_steps: list[tuple[str, str]] = []
    for scenario in plan.scenarios:
        for step in scenario.layers.ui:
            ui_steps.append((scenario.id, step.instruction))

    if not ui_steps:
        return UILayerResult(status=LayerStatus.SKIPPED)

    llm_config = resolve_computer_use_llm(context.config)
    llm = provider or OpenAICompatProvider.from_context(
        llm_config,
        context.secrets,
    )

    scenarios: list[UIScenarioResult] = []
    all_steps = []
    layer_status = LayerStatus.PASSED
    layer_error: str | None = None

    for scenario_id, instruction in ui_steps:
        loop = ActionLoop(
            instruction=instruction,
            output_dir=session.store.root,
            provider=llm,
            browser=context.config.ui.browser,
            max_steps=context.config.policy.max_ui_steps,
            max_action_retries=context.config.policy.max_ui_retries,
            max_parse_retries=context.config.policy.max_ui_parse_retries,
            ui_base_url=context.config.ui.base_url,
            smoke_route=context.config.ui.smoke_route,
            elapsed_ms_fn=session.elapsed_ms,
        )
        loop_result = loop.run()
        for screenshot in loop_result.screenshots:
            session.store.register_screenshot(screenshot)

        all_steps.extend(loop_result.steps)
        scenarios.append(
            UIScenarioResult(
                id=scenario_id,
                status=loop_result.status,
                steps_completed=len(loop_result.steps),
            )
        )
        if loop_result.status == LayerStatus.FAILED:
            layer_status = LayerStatus.FAILED
            layer_error = loop_result.error or f"UI scenario {scenario_id!r} failed"
            break

    return UILayerResult(
        status=layer_status,
        scenarios=scenarios,
        steps=all_steps,
        error=layer_error,
    )
