"""Execute UI scenarios from a VerificationPlan."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from finalstrike.computer_use.config import resolve_computer_use_llm
from finalstrike.computer_use.loop import ActionLoop, ActionLoopResult, ActionLLMProvider
from finalstrike.config.context import RepoContext
from finalstrike.config.models import (
    BrowserKind,
    LayerStatus,
    RunArtifacts,
    RunLayers,
    RunResult,
    RunStatus,
    UILayerResult,
    UIScenarioResult,
    VerificationPlan,
)
from finalstrike.providers.openai_compat import OpenAICompatProvider


def new_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")


def execute_ui_scenario(
    context: RepoContext,
    *,
    instruction: str,
    scenario_id: str = "ui-1",
    run_id: str | None = None,
    provider: ActionLLMProvider | None = None,
) -> RunResult:
    """Run a single UI instruction and write evidence under ``.finalstrike/runs/``."""
    if context.config.ui is None:
        raise ValueError("finalstrike.yaml must define a ui: block for computer-use")

    run_id = run_id or new_run_id()
    output_root = context.repo / context.config.evidence.output_dir / run_id
    llm_config = resolve_computer_use_llm(context.config)
    llm = provider or OpenAICompatProvider.from_context(
        llm_config,
        context.secrets,
    )

    loop = ActionLoop(
        instruction=instruction,
        output_dir=output_root,
        provider=llm,
        browser=context.config.ui.browser,
        max_steps=context.config.policy.max_ui_steps,
        max_action_retries=context.config.policy.max_ui_retries,
        max_parse_retries=context.config.policy.max_ui_parse_retries,
        ui_base_url=context.config.ui.base_url,
        smoke_route=context.config.ui.smoke_route,
    )
    loop_result = loop.run()

    ui_layer = UILayerResult(
        status=loop_result.status,
        scenarios=[
            UIScenarioResult(
                id=scenario_id,
                status=loop_result.status,
                steps_completed=len(loop_result.steps),
            )
        ],
        steps=loop_result.steps,
        error=loop_result.error,
    )

    run_status = (
        RunStatus.PASSED
        if loop_result.status == LayerStatus.PASSED
        else RunStatus.FAILED
    )
    result = RunResult(
        run_id=run_id,
        repo=str(context.repo.resolve()),
        status=run_status,
        layers=RunLayers(ui=ui_layer),
        artifacts=RunArtifacts(screenshots=loop_result.screenshots),
    )
    _write_run_result(output_root, result)
    return result


def execute_ui_from_plan(
    context: RepoContext,
    plan: VerificationPlan,
    *,
    scenario_id: str | None = None,
    provider: ActionLLMProvider | None = None,
) -> RunResult:
    """Execute the first UI step from a matching scenario in ``plan``."""
    for scenario in plan.scenarios:
        if scenario_id is not None and scenario.id != scenario_id:
            continue
        if not scenario.layers.ui:
            continue
        instruction = scenario.layers.ui[0].instruction
        return execute_ui_scenario(
            context,
            instruction=instruction,
            scenario_id=scenario.id,
            provider=provider,
        )
    raise ValueError(
        f"No UI steps found in plan"
        + (f" for scenario {scenario_id!r}" if scenario_id else "")
    )


def _write_run_result(output_root: Path, result: RunResult) -> Path:
    output_root.mkdir(parents=True, exist_ok=True)
    result_path = output_root / "result.json"
    with result_path.open("w", encoding="utf-8") as handle:
        json.dump(result.model_dump(mode="json"), handle, indent=2)
    return result_path


def format_run_result_json(result: RunResult) -> str:
    return json.dumps(result.model_dump(mode="json"), indent=2)
