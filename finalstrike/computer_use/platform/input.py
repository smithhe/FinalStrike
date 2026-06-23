"""OS-level mouse and keyboard input."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from abc import ABC, abstractmethod

from finalstrike.computer_use.platform.session import SessionType, detect_session_type


class InputDriver(ABC):
    @abstractmethod
    def click(self, x: int, y: int) -> None: ...

    @abstractmethod
    def type_text(self, text: str) -> None: ...

    @abstractmethod
    def key(self, combo: str) -> None: ...

    @abstractmethod
    def scroll(self, direction: str, amount: int = 3) -> None: ...

    @abstractmethod
    def focus_window(self, title_substring: str) -> None: ...


class XdotoolInputDriver(InputDriver):
    def __init__(self, binary: str = "xdotool") -> None:
        self._binary = binary

    def _run(self, *args: str) -> None:
        subprocess.run([self._binary, *args], check=True, capture_output=True)

    def click(self, x: int, y: int) -> None:
        self._run("mousemove", "--sync", str(x), str(y))
        self._run("click", "1")

    def type_text(self, text: str) -> None:
        self._run("type", "--delay", "12", "--", text)

    def key(self, combo: str) -> None:
        self._run("key", combo)

    def scroll(self, direction: str, amount: int = 3) -> None:
        button = {"up": "4", "down": "5", "left": "6", "right": "7"}.get(direction)
        if button is None:
            raise ValueError(f"unsupported scroll direction: {direction}")
        for _ in range(max(1, amount)):
            self._run("click", button)
            time.sleep(0.05)

    def focus_window(self, title_substring: str) -> None:
        result = subprocess.run(
            [self._binary, "search", "--name", title_substring],
            check=True,
            capture_output=True,
            text=True,
        )
        window_ids = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if not window_ids:
            raise RuntimeError(f"no window found matching title {title_substring!r}")
        self._run("windowactivate", "--sync", window_ids[0])


class YdotoolInputDriver(InputDriver):
    """Wayland input via ydotool (scroll via page keys; no native window focus)."""

    _SCROLL_KEYS = {
        "up": "104:1",
        "down": "105:1",
        "left": "103:1",
        "right": "106:1",
    }

    def __init__(self, binary: str = "ydotool") -> None:
        self._binary = binary

    def _run(self, *args: str) -> None:
        subprocess.run([self._binary, *args], check=True, capture_output=True)

    def click(self, x: int, y: int) -> None:
        self._run("mousemove", "--absolute", str(x), str(y))
        self._run("click", "0xC0")  # left button

    def type_text(self, text: str) -> None:
        self._run("type", text)

    def key(self, combo: str) -> None:
        mapping = {
            "Return": "28:1",
            "enter": "28:1",
            "Escape": "1:1",
            "Tab": "15:1",
        }
        code = mapping.get(combo, combo)
        self._run("key", code)

    def scroll(self, direction: str, amount: int = 3) -> None:
        key = self._SCROLL_KEYS.get(direction)
        if key is None:
            raise ValueError(f"unsupported scroll direction: {direction}")
        for _ in range(max(1, amount)):
            self._run("key", key)
            time.sleep(0.05)

    def focus_window(self, title_substring: str) -> None:
        raise NotImplementedError(
            "ydotool cannot focus windows by title; use an X11 session or XWayland "
            f"(xdotool) when focus_window is required (requested {title_substring!r})"
        )


def create_input_driver(session: SessionType | None = None) -> InputDriver:
    session = session or detect_session_type()
    xdotool = shutil.which("xdotool")
    if xdotool and (session != SessionType.WAYLAND or os.environ.get("DISPLAY")):
        return XdotoolInputDriver(xdotool)
    if session == SessionType.WAYLAND:
        ydotool = shutil.which("ydotool")
        if ydotool:
            return YdotoolInputDriver(ydotool)
        raise RuntimeError(
            "Wayland session detected but ydotool is not installed. "
            "Install ydotool or use an X11 session."
        )
    if xdotool:
        return XdotoolInputDriver(xdotool)
    raise RuntimeError(
        "xdotool is not installed. Computer-use requires xdotool (X11) or ydotool (Wayland)."
    )
