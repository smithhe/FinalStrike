"""Full run orchestration: plan → layers → evidence → HTML report."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from finalstrike.computer_use.loop import ActionLLMProvider
from finalstrike.config.context import RepoContext
from finalstrike.config.models import (
    LayerStatus,
    RunLayers,
    RunResult,
    RunStatus,
    VerificationPlan,
)
from finalstrike.env.orchestrator import EnvOrchestrator
from finalstrike.evidence import ALL_LAYERS, EvidenceSession, new_run_id
from finalstrike.orchestrator.layers import run_ui_layer
from finalstrike.planner.planner import generate_verification_plan
from finalstrike.providers.openai_compat import ChatMessage
from finalstrike.reporters.html import render_html_report
from finalstrike.runners.api import run_api_layer
from finalstrike.runners.build import run_build_layer
from finalstrike.runners.terminal import run_terminal_layer

VALID_LAYERS = frozenset(ALL_LAYERS)
DEFAULT_LAYERS: tuple[str, ...] = ALL_LAYERS


class PlannerProvider(Protocol):
    def chat_completion(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.2,
        json_mode: bool = True,
    ) -> str: ...


def parse_layers(layers: str | None) -> list[str]:
    if not layers:
        return list(DEFAULT_LAYERS)
    selected = [part.strip() for part in layers.split(",") if part.strip()]
    unknown = [layer for layer in selected if layer not in VALID_LAYERS]
    if unknown:
        raise ValueError(
            f"Unknown layer(s): {', '.join(unknown)}. "
            f"Valid: {', '.join(sorted(VALID_LAYERS))}"
        )
    return selected


def resolve_plan(
    context: RepoContext,
    plan: VerificationPlan | None,
    *,
    planner_provider: PlannerProvider | None = None,
) -> VerificationPlan:
    if plan is not None:
        return plan
    return generate_verification_plan(context, provider=planner_provider)


def execute_run(
    context: RepoContext,
    *,
    layers: list[str],
    branch: str | None = None,
    fail_fast: bool | None = None,
    skip_env: bool = False,
    health_timeout: float = 60.0,
    command_timeout: float | None = 600.0,
    plan: VerificationPlan | None = None,
    api_timeout: float = 30.0,
    planner_provider: PlannerProvider | None = None,
    ui_provider: ActionLLMProvider | None = None,
    render_html: bool = True,
) -> RunResult:
    """Execute selected verification layers and produce a complete evidence bundle."""
    policy_fail_fast = (
        context.config.policy.fail_fast if fail_fast is None else fail_fast
    )
    verification_plan = resolve_plan(
        context,
        plan,
        planner_provider=planner_provider,
    )
    effective_layers = [layer for layer in layers if not (skip_env and layer == "env")]

    run_layers = RunLayers()
    env_orchestrator: EnvOrchestrator | None = None
    abort = False

    with EvidenceSession.for_context(context, run_id=new_run_id()) as session:
        try:
            if "env" in effective_layers:
                env_orchestrator = EnvOrchestrator(
                    repo=context.repo,
                    environment=context.environment,
                    config=context.config,
                    subprocess_env=context.subprocess_env,
                    health_timeout=health_timeout,
                )
                run_layers.env = env_orchestrator.up()
                if run_layers.env.status == LayerStatus.FAILED:
                    abort = policy_fail_fast

            if "build" in effective_layers and not abort:
                run_layers.build = run_build_layer(
                    context.config.build.commands,
                    cwd=context.repo,
                    env=context.subprocess_env,
                    timeout=command_timeout,
                )
                if run_layers.build.status == LayerStatus.FAILED:
                    abort = policy_fail_fast

            if "terminal" in effective_layers and not abort:
                run_layers.terminal = run_terminal_layer(
                    context.config.tests.commands,
                    cwd=context.repo,
                    env=context.subprocess_env,
                    timeout=command_timeout,
                    max_retries=context.config.policy.max_test_retries,
                )
                if run_layers.terminal.status == LayerStatus.FAILED:
                    abort = policy_fail_fast

            if "api" in effective_layers and not abort:
                run_layers.api = run_api_layer(
                    context.config.api,
                    plan=verification_plan,
                    subprocess_env=context.subprocess_env,
                    secrets=context.secrets,
                    timeout=api_timeout,
                )
                if run_layers.api.status == LayerStatus.FAILED:
                    abort = policy_fail_fast

            if "ui" in effective_layers and not abort:
                run_layers.ui = run_ui_layer(
                    context,
                    verification_plan,
                    session,
                    provider=ui_provider,
                )
                if run_layers.ui.status == LayerStatus.FAILED:
                    abort = policy_fail_fast
        finally:
            if env_orchestrator is not None and "env" in effective_layers:
                env_orchestrator.down()

        session.persist_env_logs(run_layers)

        status = _aggregate_status(run_layers, effective_layers)
        result = RunResult(
            run_id=session.store.run_id,
            repo=str(context.repo.resolve()),
            branch=branch,
            status=status,
            layers=run_layers,
        )
        finalized = session.finalize(
            result,
            plan=verification_plan,
            requested_layers=layers,
        )
        if render_html:
            report_path = render_html_report(
                finalized,
                artifact_dir=session.store.root,
                secrets=context.secrets,
            )
            rel = session.store.relative_to_run(report_path)
            finalized = finalized.model_copy(
                update={
                    "artifacts": finalized.artifacts.model_copy(
                        update={"html_report": rel}
                    )
                }
            )
            session.store.write_result(finalized)
        return finalized


def _aggregate_status(run_layers: RunLayers, requested: list[str]) -> RunStatus:
    layer_results: list[LayerStatus] = []
    if "env" in requested and run_layers.env is not None:
        layer_results.append(run_layers.env.status)
    if "build" in requested and run_layers.build is not None:
        layer_results.append(run_layers.build.status)
    if "terminal" in requested and run_layers.terminal is not None:
        layer_results.append(run_layers.terminal.status)
    if "api" in requested and run_layers.api is not None:
        layer_results.append(run_layers.api.status)
    if "ui" in requested and run_layers.ui is not None:
        if run_layers.ui.status != LayerStatus.SKIPPED:
            layer_results.append(run_layers.ui.status)

    if any(status == LayerStatus.FAILED for status in layer_results):
        return RunStatus.FAILED
    if layer_results and all(status == LayerStatus.PASSED for status in layer_results):
        return RunStatus.PASSED
    if any(status == LayerStatus.PASSED for status in layer_results):
        return RunStatus.PARTIAL
    return RunStatus.PASSED


def _write_run_result(context: RepoContext, result: RunResult) -> Path:
    """Deprecated: prefer EvidenceSession.finalize(). Kept for compatibility."""
    from finalstrike.evidence import ArtifactStore

    store = ArtifactStore(context, run_id=result.run_id)
    return store.write_result(result)


def format_run_result_json(result: RunResult) -> str:
    return json.dumps(result.model_dump(mode="json"), indent=2)


def format_run_summary(result: RunResult, *, artifact_dir: Path) -> str:
    """Human-readable one-line summary for CLI output."""
    gap_count = len(result.gaps)
    gaps = f", {gap_count} gap(s)" if gap_count else ""
    return (
        f"Run {result.status.value}: artifacts at {artifact_dir}{gaps}"
    )
