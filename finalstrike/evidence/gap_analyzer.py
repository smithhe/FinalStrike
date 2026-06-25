"""Merge planner, runtime, and policy gaps into RunResult.gaps."""

from __future__ import annotations

from collections.abc import Callable

from finalstrike.config.models import (
    LayerStatus,
    PlanGap,
    RunLayers,
    VerificationPlan,
)

ALL_LAYERS: tuple[str, ...] = ("env", "build", "terminal", "api", "ui")

_LAYER_LABELS: dict[str, str] = {
    "env": "Environment bootstrap",
    "build": "Build layer",
    "terminal": "Terminal test layer",
    "api": "API verification layer",
    "ui": "UI verification layer",
}


def merge_gaps(
    *,
    plan: VerificationPlan | None,
    layers: RunLayers,
    requested_layers: list[str],
    all_layers: tuple[str, ...] = ALL_LAYERS,
) -> list[PlanGap]:
    """Combine planner gaps with runtime failures and skipped layers."""
    merged: list[PlanGap] = []
    seen: set[str] = set()

    def add(item: str, reason: str) -> None:
        key = item.strip().lower()
        if key in seen:
            return
        seen.add(key)
        merged.append(PlanGap(item=item, reason=reason))

    if plan is not None:
        for gap in plan.gaps:
            add(gap.item, gap.reason)

    requested = set(requested_layers)
    for layer_name in all_layers:
        if layer_name not in requested:
            add(
                _LAYER_LABELS.get(layer_name, layer_name),
                "Skipped via --layers filter",
            )

    _add_runtime_gaps(layers, add)
    return merged


def _add_runtime_gaps(
    layers: RunLayers,
    add: Callable[[str, str], None],
) -> None:
    if layers.env is not None and layers.env.status == LayerStatus.FAILED:
        reason = _truncate(layers.env.logs) or "Environment bootstrap failed"
        add(_LAYER_LABELS["env"], reason)

    if layers.build is not None and layers.build.status == LayerStatus.FAILED:
        failed = [cmd for cmd in layers.build.commands if cmd.status == LayerStatus.FAILED]
        if failed:
            cmd = failed[0]
            reason = _truncate(cmd.stderr or cmd.stdout) or f"{cmd.name} exited {cmd.exit_code}"
            add(_LAYER_LABELS["build"], reason)
        else:
            add(_LAYER_LABELS["build"], "One or more build commands failed")

    if layers.terminal is not None and layers.terminal.status == LayerStatus.FAILED:
        failed = [
            cmd for cmd in layers.terminal.commands if cmd.status == LayerStatus.FAILED
        ]
        if failed:
            cmd = failed[0]
            reason = _truncate(cmd.stderr or cmd.stdout) or f"{cmd.name} exited {cmd.exit_code}"
            add(_LAYER_LABELS["terminal"], reason)
        else:
            add(
                _LAYER_LABELS["terminal"],
                f"{layers.terminal.total_failed} test(s) failed",
            )

    if layers.api is not None and layers.api.status == LayerStatus.FAILED:
        failed = [check for check in layers.api.checks if check.status == LayerStatus.FAILED]
        if failed:
            check = failed[0]
            reason = check.error or (
                f"{check.method} {check.path} returned {check.actual_status}, "
                f"expected {check.expected_status}"
            )
            add(_LAYER_LABELS["api"], reason)
        else:
            add(_LAYER_LABELS["api"], "One or more API checks failed")

    if layers.ui is not None and layers.ui.status == LayerStatus.FAILED:
        reason = layers.ui.error or "UI scenario failed"
        add(_LAYER_LABELS["ui"], reason)


def _truncate(text: str, *, limit: int = 240) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3] + "..."
