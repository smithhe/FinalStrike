"""API HTTP check runner (Phase 4)."""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Any

import httpx

from finalstrike.config.models import (
    APIConfig,
    APIExpectation,
    APIPlanStep,
    APICheckResult,
    APILayerResult,
    HealthCheckConfig,
    LayerStatus,
    VerificationPlan,
)

RESPONSE_BODY_LIMIT = 8192
_TRUNCATION_MARKER = "\n...[truncated at 8192 bytes]"
_CONNECTION_HELP = (
    "Start services with `finalstrike env up --repo <repo>` or run "
    "`finalstrike doctor --repo <repo>` to verify prerequisites."
)


@dataclass(frozen=True)
class APICheckDefinition:
    """Single HTTP check to execute."""

    method: str
    path: str
    expect: APIExpectation
    body: Any | None = None
    request_headers: dict[str, str] | None = None


def build_api_checks(
    api_config: APIConfig,
    plan: VerificationPlan | None = None,
) -> list[APICheckDefinition]:
    """Build checks from yaml health config plus optional verification plan."""
    checks: list[APICheckDefinition] = []
    for health in api_config.health:
        checks.append(_health_to_definition(health))
    if plan is not None:
        for scenario in plan.scenarios:
            for step in scenario.layers.api:
                checks.append(_plan_step_to_definition(step))
    return checks


def run_api_layer(
    api_config: APIConfig | None,
    *,
    plan: VerificationPlan | None = None,
    subprocess_env: dict[str, str],
    secrets: dict[str, str],
    timeout: float = 30.0,
) -> APILayerResult:
    """Execute API health and plan checks against a live API."""
    if api_config is None:
        return APILayerResult(status=LayerStatus.SKIPPED, checks=[])

    checks = build_api_checks(api_config, plan)
    if not checks:
        return APILayerResult(status=LayerStatus.SKIPPED, checks=[])

    results: list[APICheckResult] = []
    layer_status = LayerStatus.PASSED
    auth_headers = _auth_headers_from_env(subprocess_env)

    with httpx.Client(
        base_url=api_config.base_url.rstrip("/"),
        timeout=timeout,
        follow_redirects=True,
    ) as client:
        for definition in checks:
            result = _run_single_check(
                client,
                definition,
                subprocess_env=subprocess_env,
                secrets=secrets,
                auth_headers=auth_headers,
            )
            results.append(result)
            if result.status == LayerStatus.FAILED:
                layer_status = LayerStatus.FAILED

    return APILayerResult(status=layer_status, checks=results)


def _health_to_definition(health: HealthCheckConfig) -> APICheckDefinition:
    return APICheckDefinition(
        method=health.method.upper(),
        path=health.path,
        expect=APIExpectation(status=health.expect_status),
    )


def _plan_step_to_definition(step: APIPlanStep) -> APICheckDefinition:
    return APICheckDefinition(
        method=step.method.upper(),
        path=step.path,
        expect=step.expect,
        body=step.body,
        request_headers=step.headers,
    )


def _auth_headers_from_env(subprocess_env: dict[str, str]) -> dict[str, str]:
    """Attach Authorization when a bearer token secret is present in env."""
    headers: dict[str, str] = {}
    for key in ("API_BEARER_TOKEN", "API_TOKEN", "BEARER_TOKEN"):
        token = subprocess_env.get(key)
        if token:
            headers["Authorization"] = f"Bearer {token}"
            break
    return headers


def _run_single_check(
    client: httpx.Client,
    definition: APICheckDefinition,
    *,
    subprocess_env: dict[str, str],
    secrets: dict[str, str],
    auth_headers: dict[str, str],
) -> APICheckResult:
    start = time.monotonic()
    method = definition.method.upper()
    path = definition.path
    headers = dict(auth_headers)
    if definition.request_headers:
        headers.update(
            _expand_env_templates(definition.request_headers, subprocess_env)
        )

    json_body: Any | None = None
    content: str | bytes | None = None
    if definition.body is not None:
        if isinstance(definition.body, (dict, list)):
            json_body = definition.body
        else:
            content = str(definition.body)

    try:
        response = client.request(
            method,
            path,
            headers=headers or None,
            json=json_body,
            content=content,
        )
    except httpx.HTTPError as exc:
        duration_ms = int((time.monotonic() - start) * 1000)
        return APICheckResult(
            method=method,
            path=path,
            status=LayerStatus.FAILED,
            expected_status=definition.expect.status,
            actual_status=None,
            duration_ms=duration_ms,
            response_body="",
            error=f"{exc}. {_CONNECTION_HELP}",
        )

    duration_ms = int((time.monotonic() - start) * 1000)
    body_text = _format_response_body(response)
    body_text = sanitize_response_body(body_text, secrets)

    failures = _evaluate_expectations(response, definition.expect)
    passed = not failures
    error = "; ".join(failures) if failures else None

    return APICheckResult(
        method=method,
        path=path,
        status=LayerStatus.PASSED if passed else LayerStatus.FAILED,
        expected_status=definition.expect.status,
        actual_status=response.status_code,
        duration_ms=duration_ms,
        response_body=body_text,
        error=error,
    )


def _evaluate_expectations(
    response: httpx.Response,
    expect: APIExpectation,
) -> list[str]:
    failures: list[str] = []
    if response.status_code != expect.status:
        failures.append(
            f"expected status {expect.status}, got {response.status_code}"
        )

    if expect.headers:
        for name, expected_value in expect.headers.items():
            actual = _response_header(response, name)
            if actual is None:
                failures.append(f"missing response header {name}")
            elif actual != expected_value:
                failures.append(
                    f"header {name}: expected {expected_value!r}, got {actual!r}"
                )

    if expect.json_paths:
        try:
            payload = response.json()
        except json.JSONDecodeError:
            failures.append("response is not valid JSON for json_paths assertions")
            payload = None

        if payload is not None:
            for path, expected in expect.json_paths.items():
                try:
                    actual = extract_json_path(payload, path)
                except (KeyError, IndexError, TypeError, ValueError):
                    failures.append(f"json_paths missing path {path!r}")
                    continue
                if actual != expected:
                    failures.append(
                        f"json_paths {path}: expected {expected!r}, got {actual!r}"
                    )

    return failures


def extract_json_path(payload: Any, path: str) -> Any:
    """Resolve a dot-separated path into JSON (supports list indices)."""
    current: Any = payload
    for part in path.split("."):
        if isinstance(current, list):
            current = current[int(part)]
        elif isinstance(current, dict):
            if part not in current:
                raise KeyError(part)
            current = current[part]
        else:
            raise TypeError(f"cannot traverse {type(current).__name__} with {part!r}")
    return current


def _response_header(response: httpx.Response, name: str) -> str | None:
    for header_name, value in response.headers.items():
        if header_name.lower() == name.lower():
            return value
    return None


def _format_response_body(response: httpx.Response) -> str:
    content_type = response.headers.get("content-type", "")
    if "application/json" in content_type.lower():
        try:
            return json.dumps(response.json(), indent=2)
        except json.JSONDecodeError:
            pass
    if response.headers.get("content-type", "").startswith("text/"):
        return response.text
    raw = response.content
    if not raw:
        return ""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return f"[binary, {len(raw)} bytes]"


def sanitize_response_body(text: str, secrets: dict[str, str]) -> str:
    """Redact secrets and cap stored response body size."""
    redacted = text
    for value in secrets.values():
        if value and len(value) >= 4:
            redacted = redacted.replace(value, "***")
    redacted = re.sub(
        r"(Bearer\s+)[A-Za-z0-9._~+/=-]+",
        r"\1***",
        redacted,
        flags=re.IGNORECASE,
    )
    if len(redacted) > RESPONSE_BODY_LIMIT:
        keep = RESPONSE_BODY_LIMIT - len(_TRUNCATION_MARKER)
        return redacted[:keep] + _TRUNCATION_MARKER
    return redacted


def _expand_env_templates(
    headers: dict[str, str],
    subprocess_env: dict[str, str],
) -> dict[str, str]:
    expanded: dict[str, str] = {}
    for name, value in headers.items():
        expanded[name] = _expand_env_value(value, subprocess_env)
    return expanded


def _expand_env_value(value: str, subprocess_env: dict[str, str]) -> str:
    def replacer(match: re.Match[str]) -> str:
        key = match.group(1) or match.group(2)
        return subprocess_env.get(key, match.group(0))

    return re.sub(r"\$\{([^}]+)\}|\$([A-Za-z_][A-Za-z0-9_]*)", replacer, value)
