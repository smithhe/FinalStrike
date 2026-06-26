"""Full-desktop video recording for verification runs."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from finalstrike.evidence.store import ArtifactStore


@dataclass
class VideoRecorder:
    """Start/stop desktop capture for a single run."""

    output_path: Path
    enabled: bool = True
    _process: subprocess.Popen[bytes] | None = field(default=None, init=False, repr=False)
    _backend: str | None = field(default=None, init=False, repr=False)
    _started_at: float | None = field(default=None, init=False, repr=False)
    _error: str | None = field(default=None, init=False, repr=False)
    _stderr_log: Path | None = field(default=None, init=False, repr=False)
    _capture_path: Path | None = field(default=None, init=False, repr=False)

    @property
    def error(self) -> str | None:
        return self._error

    @property
    def backend(self) -> str | None:
        return self._backend

    def elapsed_ms(self) -> int:
        if self._started_at is None:
            return 0
        return int((time.monotonic() - self._started_at) * 1000)

    def start(self) -> bool:
        """Begin recording. Returns True when a recorder process is running."""
        if not self.enabled:
            return False
        if self._process is not None:
            return True

        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        command, backend, capture_path = _build_recorder_command(self.output_path)
        if command is None:
            self._error = backend
            return False

        self._capture_path = capture_path
        stderr_log = self.output_path.parent / "logs" / "video-recorder.log"
        stderr_log.parent.mkdir(parents=True, exist_ok=True)
        self._stderr_log = stderr_log

        try:
            stderr_handle = stderr_log.open("w", encoding="utf-8")
            self._process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=stderr_handle,
                start_new_session=True,
            )
        except OSError as exc:
            self._error = str(exc)
            self._process = None
            return False

        time.sleep(0.25)
        if self._process.poll() is not None:
            self._error = _read_recorder_failure(stderr_log, self._process.returncode)
            self._process = None
            return False

        self._backend = backend
        self._started_at = time.monotonic()
        return True

    def stop(self) -> Path | None:
        """Stop recording and return a browser-playable video path when available."""
        if self._process is None:
            return self._playback_output_path()

        process = self._process
        self._process = None
        if process.poll() is None:
            _terminate_process(process, backend=self._backend)

        capture_path = self._capture_path or self.output_path
        if not _valid_file(capture_path):
            if self._error is None and self._stderr_log is not None:
                self._error = _read_recorder_failure(self._stderr_log, None)
            return None

        if capture_path.resolve() == self.output_path.resolve():
            return self.output_path

        playback = transcode_for_browser_playback(
            capture_path,
            self.output_path,
            error_out=self,
        )
        return playback

    def __enter__(self) -> VideoRecorder:
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        del exc_type, exc, tb
        self.stop()

    def _playback_output_path(self) -> Path | None:
        if _valid_file(self.output_path):
            return self.output_path
        capture_path = self._capture_path
        if capture_path is not None and _valid_file(capture_path):
            return transcode_for_browser_playback(
                capture_path,
                self.output_path,
                error_out=self,
            )
        if self._error is None and self._stderr_log is not None:
            self._error = _read_recorder_failure(self._stderr_log, None)
        return None


def _valid_file(path: Path) -> bool:
    return path.is_file() and path.stat().st_size > 0


def transcode_for_browser_playback(
    source: Path,
    destination: Path,
    *,
    error_out: VideoRecorder | None = None,
) -> Path | None:
    """Transcode a capture file into H.264 MP4 suitable for HTML5 playback."""
    if source.resolve() == destination.resolve():
        if _valid_file(destination):
            return destination
        return None

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        if error_out is not None:
            error_out._error = "ffmpeg not found on PATH (needed to prepare desktop.mp4)"
        return source if _valid_file(source) else None

    destination.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-i",
            str(source),
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(destination),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0 and _valid_file(destination):
        return destination

    detail = " ".join((result.stderr or "").split())
    if len(detail) > 200:
        detail = detail[:197] + "..."
    if error_out is not None:
        error_out._error = detail or "failed to transcode desktop recording to MP4"
    return source if _valid_file(source) else None


def _terminate_process(
    process: subprocess.Popen[bytes],
    *,
    backend: str | None,
) -> None:
    if process.poll() is not None:
        return
    if backend and backend.startswith("wf-recorder"):
        try:
            process.send_signal(signal.SIGINT)
            process.wait(timeout=10)
            if process.poll() is not None:
                return
        except (OSError, ProcessLookupError, subprocess.TimeoutExpired):
            pass
    try:
        if process.stdin is not None and not process.stdin.closed:
            process.stdin.write(b"q")
            process.stdin.flush()
            process.stdin.close()
            process.wait(timeout=15)
            if process.poll() is not None:
                return
    except (BrokenPipeError, OSError, ProcessLookupError, subprocess.TimeoutExpired):
        pass
    try:
        process.send_signal(signal.SIGINT)
    except (OSError, ProcessLookupError):
        process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _read_recorder_failure(stderr_log: Path, exit_code: int | None) -> str:
    detail = ""
    if stderr_log.is_file():
        detail = " ".join(stderr_log.read_text(encoding="utf-8").split())
        if len(detail) > 200:
            detail = detail[:197] + "..."
    if detail:
        return detail
    if exit_code is not None:
        return f"desktop recorder exited with code {exit_code}"
    return "desktop recorder produced no video output"


def _desktop_video_size() -> tuple[int, int]:
    try:
        import mss

        with mss.MSS() as sct:
            monitor = sct.monitors[0]
            width = int(monitor["width"])
            height = int(monitor["height"])
    except Exception:
        width, height = 1920, 1080
    return _even_dimensions(width, height)


def _even_dimensions(width: int, height: int) -> tuple[int, int]:
    return width - (width % 2), height - (height % 2)


def _ffmpeg_x11grab_command(
    output_path: Path,
    *,
    display: str,
    backend: str,
) -> tuple[list[str], str]:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        return [], backend
    width, height = _desktop_video_size()
    return (
        [
            ffmpeg,
            "-y",
            "-f",
            "x11grab",
            "-video_size",
            f"{width}x{height}",
            "-framerate",
            "15",
            "-i",
            display,
            "-vf",
            "scale=trunc(iw/2)*2:trunc(ih/2)*2",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(output_path),
        ],
        backend,
    )


def _build_recorder_command(
    playback_path: Path,
) -> tuple[list[str] | None, str, Path | None]:
    from finalstrike.computer_use.platform.session import SessionType, detect_session_type

    session = detect_session_type()
    if session == SessionType.X11:
        display = os.environ.get("DISPLAY", ":0")
        command, backend = _ffmpeg_x11grab_command(
            playback_path,
            display=display,
            backend="ffmpeg-x11grab",
        )
        if not command:
            return None, "ffmpeg not found on PATH", None
        return command, backend, playback_path

    if session == SessionType.WAYLAND:
        wf_recorder = shutil.which("wf-recorder")
        if wf_recorder is not None:
            capture_path = playback_path.with_name(ArtifactStore.RAW_VIDEO_FILENAME)
            return (
                [
                    wf_recorder,
                    "-f",
                    str(capture_path),
                ],
                "wf-recorder",
                capture_path,
            )
        display = os.environ.get("DISPLAY")
        if display:
            command, backend = _ffmpeg_x11grab_command(
                playback_path,
                display=display,
                backend="ffmpeg-x11grab-xwayland",
            )
            if command:
                return command, backend, playback_path
        return None, (
            "wf-recorder not found on PATH for Wayland session "
            "(install wf-recorder or ensure DISPLAY is set for XWayland)"
        ), None

    display = os.environ.get("DISPLAY")
    if display:
        command, backend = _ffmpeg_x11grab_command(
            playback_path,
            display=display,
            backend="ffmpeg-x11grab-fallback",
        )
        if command:
            return command, backend, playback_path
    return None, "no supported desktop video backend for current session", None
