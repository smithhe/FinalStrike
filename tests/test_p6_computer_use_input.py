"""Unit tests for computer-use input drivers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from finalstrike.computer_use.platform.input import YdotoolInputDriver


def test_ydotool_scroll_uses_wheel_mousemove() -> None:
    driver = YdotoolInputDriver(binary="ydotool")
    with patch.object(driver, "_run") as mock_run:
        driver.scroll("down", 2)
    assert mock_run.call_args_list == [
        (("mousemove", "--wheel", "--", "0", "-1"),),
        (("mousemove", "--wheel", "--", "0", "-1"),),
    ]
