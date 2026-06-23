"""Unit tests for computer-use input drivers."""

from __future__ import annotations

import pytest
from subprocess import CalledProcessError
from unittest.mock import patch

from finalstrike.computer_use.platform.input import YdotoolInputDriver


def test_ydotool_scroll_uses_wheel_mousemove() -> None:
    driver = YdotoolInputDriver(binary="ydotool")
    with patch.object(driver, "_run") as mock_run:
        driver.scroll("down", 2)
    assert mock_run.call_args_list == [
        (("mousemove", "--wheel", "--", "0", "-1"),),
        (("mousemove", "--wheel", "--", "0", "-1"),),
    ]


def test_ydotool_run_wraps_subprocess_errors() -> None:
    driver = YdotoolInputDriver(binary="ydotool")
    with patch("finalstrike.computer_use.platform.input.subprocess.run") as mock_run:
        mock_run.side_effect = CalledProcessError(1, "ydotool", stderr=b"boom")
        with pytest.raises(RuntimeError, match="ydotool failed"):
            driver.click(1, 1)
