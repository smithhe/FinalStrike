"""Accessibility context for the action loop."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass

from finalstrike.computer_use.platform.session import SessionType, detect_session_type


@dataclass(frozen=True)
class AccessibilitySnapshot:
    """Lightweight a11y summary passed to the vision LLM."""

    session: SessionType
    windows: list[str]

    def summary(self) -> str:
        if not self.windows:
            return f"session={self.session.value}; visible_windows=(none)"
        lines = [f"session={self.session.value}", "visible_windows:"]
        lines.extend(f"  - {title}" for title in self.windows[:20])
        if len(self.windows) > 20:
            lines.append(f"  ... and {len(self.windows) - 20} more")
        return "\n".join(lines)


class AccessibilityDriver:
    """Collect visible window titles as a pragmatic a11y tree for P6."""

    def __init__(self, *, session: SessionType | None = None) -> None:
        self._session = session or detect_session_type()
        self._xdotool = shutil.which("xdotool")

    def capture(self) -> AccessibilitySnapshot:
        windows: list[str] = []
        if self._xdotool:
            windows = _list_x11_window_titles(self._xdotool)
        return AccessibilitySnapshot(session=self._session, windows=windows)


def _list_x11_window_titles(xdotool: str) -> list[str]:
    try:
        search = subprocess.run(
            [xdotool, "search", "--onlyvisible", "."],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError:
        return []

    titles: list[str] = []
    for window_id in search.stdout.splitlines():
        window_id = window_id.strip()
        if not window_id:
            continue
        try:
            name = subprocess.run(
                [xdotool, "getwindowname", window_id],
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError:
            continue
        title = name.stdout.strip()
        if title:
            titles.append(title)
    return titles
