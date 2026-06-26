"""Full-desktop video recording for verification runs."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path


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
        command, backend = _build_recorder_command(self.output_path)
        if command is None:
            self._error = backend
            return False

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
        """Stop recording and return the output path when the file exists."""
        if self._process is None:
            return self._valid_output_path()

        process = self._process
        self._process = None
        if process.poll() is None:
            _terminate_process(process)

        return self._valid_output_path()

    def __enter__(self) -> VideoRecorder:
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        del exc_type, exc, tb
        self.stop()

    def _valid_output_path(self) -> Path | None:
        if self.output_path.is_file() and self.output_path.stat().st_size > 0:
            return self.output_path
        if self._error is None and self._stderr_log is not None:
            self._error = _read_recorder_failure(self._stderr_log, None)
        return None


def _terminate_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
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
            return int(monitor["width"]), int(monitor["height"])
    except Exception:
        return 1920, 1080


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
            "-c:v",
            "libvpx",
            "-pix_fmt",
            "yuv420p",
            "-deadline",
            "realtime",
            "-cpu-used",
            "4",
            "-b:v",
            "1M",
            "-f",
            "webm",
            str(output_path),
        ],
        backend,
    )


def _build_recorder_command(output_path: Path) -> tuple[list[str] | None, str]:
    from finalstrike.computer_use.platform.session import SessionType, detect_session_type

    session = detect_session_type()
    if session == SessionType.X11:
        display = os.environ.get("DISPLAY", ":0")
        command, _ = _ffmpeg_x11grab_command(
            output_path,
            display=display,
            backend="ffmpeg-x11grab",
        )
        if not command:
            return None, "ffmpeg not found on PATH"
        return command, "ffmpeg-x11grab"

    if session == SessionType.WAYLAND:
        wf_recorder = shutil.which("wf-recorder")
        if wf_recorder is not None:
            return (
                [
                    wf_recorder,
                    "-f",
                    str(output_path),
                ],
                "wf-recorder",
            )
        display = os.environ.get("DISPLAY")
        if display:
            command, _ = _ffmpeg_x11grab_command(
                output_path,
                display=display,
                backend="ffmpeg-x11grab-xwayland",
            )
            if command:
                return command, "ffmpeg-x11grab-xwayland"
        return None, (
            "wf-recorder not found on PATH for Wayland session "
            "(install wf-recorder or ensure DISPLAY is set for XWayland)"
        )

    display = os.environ.get("DISPLAY")
    if display:
        command, _ = _ffmpeg_x11grab_command(
            output_path,
            display=display,
            backend="ffmpeg-x11grab-fallback",
        )
        if command:
            return command, "ffmpeg-x11grab-fallback"
    return None, "no supported desktop video backend for current session"
