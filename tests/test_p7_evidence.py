"""Tests for P7 evidence recorder, artifact store, and gap analyzer."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from finalstrike.config.context import load_repo_context
from finalstrike.config.models import (
    APICheckResult,
    APILayerResult,
    BuildCommandResult,
    BuildLayerResult,
    EnvLayerResult,
    LayerStatus,
    PlanGap,
    RunLayers,
    RunResult,
    RunStatus,
    TerminalCommandResult,
    TerminalLayerResult,
    UILayerResult,
    VerificationPlan,
)
from finalstrike.evidence.gap_analyzer import merge_gaps
from finalstrike.evidence.recorder import VideoRecorder
from finalstrike.evidence.session import EvidenceSession
from finalstrike.evidence.store import ArtifactStore, new_run_id

from tests.conftest import FIXTURE_REPO


def test_new_run_id_format() -> None:
    run_id = new_run_id()
    assert run_id.endswith("Z")
    assert "T" in run_id


def test_artifact_store_paths() -> None:
    context = load_repo_context(FIXTURE_REPO)
    store = ArtifactStore(context, run_id="2026-06-20T14-30-00Z")
    store.ensure_dirs()

    assert store.root == FIXTURE_REPO / ".finalstrike/runs/2026-06-20T14-30-00Z"
    assert store.screenshots_dir.is_dir()
    assert store.logs_dir.is_dir()
    assert store.video_path.name == "desktop.webm"

    registered = store.register_screenshot("screenshots/step-001.png")
    assert registered == "screenshots/step-001.png"
    assert store.screenshots == ["screenshots/step-001.png"]


def test_artifact_store_write_result() -> None:
    context = load_repo_context(FIXTURE_REPO)
    store = ArtifactStore(context, run_id="2026-06-20T14-30-00Z")
    result = RunResult(
        run_id=store.run_id,
        repo=str(FIXTURE_REPO),
        status=RunStatus.PASSED,
    )
    path = store.write_result(result)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["status"] == "passed"
    assert payload["run_id"] == "2026-06-20T14-30-00Z"
    path.unlink()
    store.screenshots_dir.rmdir()
    store.logs_dir.rmdir()
    store.root.rmdir()


def test_merge_gaps_includes_planner_and_skipped_layers() -> None:
    plan = VerificationPlan(
        gaps=[PlanGap(item="OAuth login", reason="Not in acceptance criteria")]
    )
    layers = RunLayers()
    gaps = merge_gaps(plan=plan, layers=layers, requested_layers=["terminal"])
    items = {gap.item for gap in gaps}
    assert "OAuth login" in items
    assert "Environment bootstrap" in items
    assert "Build layer" in items
    assert "API verification layer" in items
    assert "UI verification layer" in items


def test_merge_gaps_deduplicates_items() -> None:
    plan = VerificationPlan(
        gaps=[PlanGap(item="Build layer", reason="Planner noted missing build")]
    )
    layers = RunLayers(
        build=BuildLayerResult(
            status=LayerStatus.FAILED,
            commands=[
                BuildCommandResult(
                    name="install",
                    status=LayerStatus.FAILED,
                    exit_code=1,
                    duration_ms=10,
                    stderr="pip install failed",
                )
            ],
        )
    )
    gaps = merge_gaps(plan=plan, layers=layers, requested_layers=["build"])
    build_gaps = [gap for gap in gaps if gap.item == "Build layer"]
    assert len(build_gaps) == 1


def test_merge_gaps_runtime_failures() -> None:
    layers = RunLayers(
        terminal=TerminalLayerResult(
            status=LayerStatus.FAILED,
            commands=[
                TerminalCommandResult(
                    name="unit",
                    status=LayerStatus.FAILED,
                    exit_code=1,
                    duration_ms=50,
                    total_failed=2,
                    stderr="2 failed",
                )
            ],
            total_failed=2,
        ),
        api=APILayerResult(
            status=LayerStatus.FAILED,
            checks=[
                APICheckResult(
                    method="GET",
                    path="/health",
                    status=LayerStatus.FAILED,
                    expected_status=200,
                    actual_status=503,
                    error="connection refused",
                )
            ],
        ),
        ui=UILayerResult(status=LayerStatus.FAILED, error="browser launch failed"),
    )
    gaps = merge_gaps(plan=None, layers=layers, requested_layers=["terminal", "api", "ui"])
    reasons = {gap.item: gap.reason for gap in gaps}
    assert "connection refused" in reasons["API verification layer"]
    assert "browser launch failed" in reasons["UI verification layer"]


@patch("finalstrike.evidence.recorder._build_recorder_command")
def test_video_recorder_starts_and_stops(mock_build: MagicMock, tmp_path: Path) -> None:
    output = tmp_path / "desktop.webm"
    process = MagicMock()
    process.poll.return_value = None
    process.wait.return_value = 0
    mock_build.return_value = (["ffmpeg", str(output)], "ffmpeg-x11grab")

    with patch("finalstrike.evidence.recorder.subprocess.Popen", return_value=process) as popen:
        recorder = VideoRecorder(output)
        assert recorder.start() is True
        assert recorder.elapsed_ms() >= 0
        output.write_bytes(b"webm")
        stopped = recorder.stop()

    assert stopped == output
    popen.assert_called_once()
    process.send_signal.assert_called_once()
    process.wait.assert_called()


def test_evidence_session_finalize_writes_result() -> None:
    context = load_repo_context(FIXTURE_REPO)
    store = ArtifactStore(context, run_id="2026-06-20T14-30-00Z")
    session = EvidenceSession(store=store, record_video=False)
    with session:
        result = RunResult(
            run_id=store.run_id,
            repo=str(FIXTURE_REPO),
            status=RunStatus.PASSED,
            layers=RunLayers(
                env=EnvLayerResult(
                    status=LayerStatus.PASSED,
                    duration_ms=10,
                    logs="started services",
                )
            ),
        )
        finalized = session.finalize(
            result,
            plan=VerificationPlan(
                gaps=[PlanGap(item="OAuth", reason="not configured")]
            ),
            requested_layers=["env"],
        )

    assert finalized.gaps
    assert store.result_path.is_file()
    payload = json.loads(store.result_path.read_text(encoding="utf-8"))
    assert payload["gaps"][0]["item"] == "OAuth"
    store.result_path.unlink()
    if store.logs_dir.exists() and not any(store.logs_dir.iterdir()):
        store.logs_dir.rmdir()
    store.screenshots_dir.rmdir()
    store.root.rmdir()


def test_evidence_session_records_video_gap_when_recording_fails() -> None:
    context = load_repo_context(FIXTURE_REPO)
    store = ArtifactStore(context, run_id="2026-06-20T14-30-00Z")
    session = EvidenceSession(store=store, record_video=True)
    session._recorder = VideoRecorder(store.video_path, enabled=False)
    session._recorder._error = "ffmpeg not found on PATH"
    result = RunResult(
        run_id=store.run_id,
        repo=str(FIXTURE_REPO),
        status=RunStatus.PASSED,
    )
    finalized = session.finalize(result, plan=None, requested_layers=["ui"])
    video_gaps = [gap for gap in finalized.gaps if gap.item == "Desktop video recording"]
    assert len(video_gaps) == 1
    assert "ffmpeg not found" in video_gaps[0].reason


def test_run_result_schema_export_matches_model() -> None:
    schema = RunResult.model_json_schema()
    assert schema["title"] == "RunResult"
    assert "run_id" in schema["properties"]
    assert "artifacts" in schema["properties"]
