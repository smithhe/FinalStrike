"""Parse pytest terminal output for pass/fail counts."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class PytestSummary:
    """Aggregated pytest result counts from terminal output."""

    total_passed: int = 0
    total_failed: int = 0
    total_errors: int = 0
    total_skipped: int = 0

    @property
    def total_run(self) -> int:
        return self.total_passed + self.total_failed + self.total_errors

    @property
    def success(self) -> bool:
        return self.total_failed == 0 and self.total_errors == 0


_COUNT_PATTERN = re.compile(
    r"(?:(\d+)\s+passed)|(?:(\d+)\s+failed)|(?:(\d+)\s+error)|(?:(\d+)\s+skipped)",
    re.IGNORECASE,
)


def parse_pytest_output(output: str) -> PytestSummary:
    """Extract pass/fail/error counts from pytest stdout/stderr."""
    passed = failed = errors = skipped = 0
    for match in _COUNT_PATTERN.finditer(output):
        if match.group(1):
            passed = int(match.group(1))
        if match.group(2):
            failed = int(match.group(2))
        if match.group(3):
            errors = int(match.group(3))
        if match.group(4):
            skipped = int(match.group(4))
    return PytestSummary(
        total_passed=passed,
        total_failed=failed,
        total_errors=errors,
        total_skipped=skipped,
    )
