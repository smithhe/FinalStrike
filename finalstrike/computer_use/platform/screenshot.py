"""Full-desktop screenshot capture."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path

import mss
import mss.tools


@dataclass(frozen=True)
class Screenshot:
    png_bytes: bytes
    width: int
    height: int

    def save(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.png_bytes)
        return path

    def as_data_url(self) -> str:
        encoded = base64.b64encode(self.png_bytes).decode("ascii")
        return f"data:image/png;base64,{encoded}"


def _png_dimensions(png_bytes: bytes) -> tuple[int, int]:
    """Read width/height from a PNG header without extra dependencies."""
    if len(png_bytes) >= 24 and png_bytes[:8] == b"\x89PNG\r\n\x1a\n":
        width = int.from_bytes(png_bytes[16:20], "big")
        height = int.from_bytes(png_bytes[20:24], "big")
        return width, height
    return 0, 0


class ScreenshotDriver:
    """Capture the full desktop as PNG."""

    def capture(self) -> Screenshot:
        try:
            return self._capture_mss()
        except Exception:
            return self._capture_subprocess()

    def _capture_mss(self) -> Screenshot:
        with mss.MSS() as sct:
            monitor = sct.monitors[0]
            shot = sct.grab(monitor)
            png_bytes = mss.tools.to_png(shot.rgb, shot.size)
            return Screenshot(
                png_bytes=png_bytes,
                width=shot.width,
                height=shot.height,
            )

    def _capture_subprocess(self) -> Screenshot:
        import shutil
        import subprocess
        import tempfile

        scrot = shutil.which("scrot")
        if scrot is None:
            raise RuntimeError(
                "desktop screenshot failed (mss) and scrot is not installed"
            )
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            path = Path(tmp.name)
        try:
            subprocess.run([scrot, "-o", str(path)], check=True, capture_output=True)
            png_bytes = path.read_bytes()
        finally:
            path.unlink(missing_ok=True)
        width, height = _png_dimensions(png_bytes)
        return Screenshot(png_bytes=png_bytes, width=width, height=height)
