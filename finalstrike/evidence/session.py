"""Evidence recording session wrapping artifact store and video capture."""

from __future__ import annotations

from dataclasses import dataclass, field

from finalstrike.config.context import RepoContext
from finalstrike.config.models import PlanGap, RunArtifacts, RunLayers, RunResult, VerificationPlan
from finalstrike.evidence.gap_analyzer import merge_gaps
from finalstrike.evidence.recorder import VideoRecorder
from finalstrike.evidence.store import ArtifactStore


@dataclass
class EvidenceSession:
    """Manage run artifacts and optional desktop video for a verification run."""

    store: ArtifactStore
    record_video: bool = True
    _recorder: VideoRecorder | None = field(default=None, init=False, repr=False)

    @classmethod
    def for_context(
        cls,
        context: RepoContext,
        *,
        run_id: str | None = None,
    ) -> EvidenceSession:
        store = ArtifactStore(context, run_id=run_id)
        return cls(store=store, record_video=context.config.evidence.video)

    def __enter__(self) -> EvidenceSession:
        self.store.ensure_dirs()
        if self.record_video:
            self._recorder = VideoRecorder(
                self.store.video_path,
                enabled=True,
            )
            self._recorder.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        del exc_type, exc, tb
        if self._recorder is not None:
            self._recorder.stop()

    def elapsed_ms(self) -> int:
        if self._recorder is None:
            return 0
        return self._recorder.elapsed_ms()

    def finalize(
        self,
        result: RunResult,
        *,
        plan: VerificationPlan | None,
        requested_layers: list[str],
    ) -> RunResult:
        """Attach video, screenshots, merged gaps, and write result.json."""
        artifacts = RunArtifacts(
            video=result.artifacts.video,
            screenshots=list(result.artifacts.screenshots or self.store.screenshots),
            html_report=result.artifacts.html_report,
        )
        if self._recorder is not None:
            video_path = self._recorder.stop()
            if video_path is not None:
                artifacts.video = self.store.relative_to_run(video_path)

        gaps = merge_gaps(
            plan=plan,
            layers=result.layers,
            requested_layers=requested_layers,
        )
        if self.record_video and artifacts.video is None:
            reason = (
                self._recorder.error
                if self._recorder is not None and self._recorder.error
                else "desktop video recorder did not produce output"
            )
            gaps.append(
                PlanGap(
                    item="Desktop video recording",
                    reason=reason,
                )
            )

        finalized = result.model_copy(
            update={
                "run_id": self.store.run_id,
                "artifacts": artifacts,
                "gaps": gaps,
            }
        )
        self.store.write_result(finalized)
        return finalized

    def persist_env_logs(self, layers: RunLayers) -> str | None:
        if layers.env is None or not layers.env.logs:
            return None
        return self.store.write_log("env.log", layers.env.logs)
