"""Full-desktop video recording for verification runs."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from finalstrike.computer_use.platform.session import SessionType, detect_session_type


@dataclass
class VideoRecorder:
    """Start/stop desktop capture for a single run."""

    output_path: Path
    enabled: bool = True
    _process: subprocess.Popen[bytes] | None = field(default=None, init=False, repr=False)
    _backend: str | None = field(default=None, init=False, repr=False)
    _started_at: float | None = field(default=None, init=False, repr=False)
    _error: str | None = field(default=None, init=False, repr=False)

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

        try:
            self._process = subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError as exc:
            self._error = str(exc)
            self._process = None
            return False

        self._backend = backend
        self._started_at = time.monotonic()
        return True

    def stop(self) -> Path | None:
        """Stop recording and return the output path when the file exists."""
        if self._process is None:
            return self.output_path if self.output_path.is_file() else None

        process = self._process
        self._process = None
        if process.poll() is None:
            _terminate_process(process)

        if self.output_path.is_file() and self.output_path.stat().st_size > 0:
            return self.output_path
        return None

    def __enter__(self) -> VideoRecorder:
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        del exc_type, exc, tb
        self.stop()


def _terminate_process(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGINT)
    except (OSError, ProcessLookupError):
        process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            process.kill()
        process.wait(timeout=5)


def _build_recorder_command(output_path: Path) -> tuple[list[str] | None, str]:
    session = detect_session_type()
    if session == SessionType.X11:
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg is None:
            return None, "ffmpeg not found on PATH"
        display = os.environ.get("DISPLAY", ":0")
        return (
            [
                ffmpeg,
                "-y",
                "-f",
                "x11grab",
                "-video_size",
                "1920x1080",
                "-framerate",
                "15",
                "-i",
                display,
                "-c:v",
                "libvpx-vp9",
                "-b:v",
                "1M",
                str(output_path),
            ],
            "ffmpeg-x11grab",
        )

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
        return None, "wf-recorder not found on PATH for Wayland session"

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is not None and os.environ.get("DISPLAY"):
        display = os.environ["DISPLAY"]
        return (
            [
                ffmpeg,
                "-y",
                "-f",
                "x11grab",
                "-video_size",
                "1920x1080",
                "-framerate",
                "15",
                "-i",
                display,
                "-c:v",
                "libvpx-vp9",
                "-b:v",
                "1M",
                str(output_path),
            ],
            "ffmpeg-x11grab-fallback",
        )
    return None, "no supported desktop video backend for current session"
