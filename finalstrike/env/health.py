"""HTTP health-check polling for running services."""

from __future__ import annotations

import time
from dataclasses import dataclass

import httpx

from finalstrike.config.models import HealthCheckConfig


@dataclass(frozen=True)
class HealthCheckOutcome:
    """Result of a single health check attempt series."""

    check: HealthCheckConfig
    passed: bool
    status_code: int | None
    error: str | None
    duration_ms: int


def _check_once(
    client: httpx.Client,
    base_url: str,
    check: HealthCheckConfig,
) -> tuple[bool, int | None, str | None]:
    url = f"{base_url.rstrip('/')}{check.path}"
    method = check.method.upper()
    try:
        response = client.request(method, url)
    except httpx.HTTPError as exc:
        return False, None, str(exc)
    passed = response.status_code == check.expect_status
    error = None if passed else f"expected {check.expect_status}, got {response.status_code}"
    return passed, response.status_code, error


def wait_for_health(
    base_url: str,
    checks: list[HealthCheckConfig],
    *,
    timeout: float = 60.0,
    interval: float = 0.5,
) -> list[HealthCheckOutcome]:
    """Poll health endpoints until all pass or timeout."""
    if not checks:
        return []

    deadline = time.monotonic() + timeout
    outcomes: list[HealthCheckOutcome] = []
    pending = list(checks)

    with httpx.Client(timeout=5.0) as client:
        while pending and time.monotonic() < deadline:
            still_pending: list[HealthCheckConfig] = []
            for check in pending:
                start = time.monotonic()
                passed, status_code, error = _check_once(client, base_url, check)
                duration_ms = int((time.monotonic() - start) * 1000)
                if passed:
                    outcomes.append(
                        HealthCheckOutcome(
                            check=check,
                            passed=True,
                            status_code=status_code,
                            error=None,
                            duration_ms=duration_ms,
                        )
                    )
                else:
                    still_pending.append(check)
            pending = still_pending
            if pending:
                time.sleep(interval)

        for check in pending:
            start = time.monotonic()
            passed, status_code, error = _check_once(client, base_url, check)
            duration_ms = int((time.monotonic() - start) * 1000)
            outcomes.append(
                HealthCheckOutcome(
                    check=check,
                    passed=passed,
                    status_code=status_code,
                    error=error if not passed else None,
                    duration_ms=duration_ms,
                )
            )

    return outcomes
