"""Tests for the OpenAI-compatible LLM provider adapter."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
from openai import APIStatusError

from finalstrike.config.models import LLMConfig, LLMProvider
from finalstrike.providers.openai_compat import (
    OpenAICompatProvider,
    _json_mode_unsupported,
    _temperature_unsupported,
)


def _api_status_error(message: str, *, status_code: int = 400) -> APIStatusError:
    request = httpx.Request("POST", "[REDACTED]/v1/chat/completions")
    response = httpx.Response(
        status_code,
        request=request,
        json={"error": {"message": message}},
    )
    return APIStatusError(message, response=response, body={"error": {"message": message}})


def test_temperature_unsupported_detects_openai_reasoning_models() -> None:
    exc = _api_status_error(
        "Unsupported value: 'temperature' does not support 0.2 with this model. "
        "Only the default (1) value is supported."
    )
    assert _temperature_unsupported(exc)
    assert not _json_mode_unsupported(exc)


def test_json_mode_unsupported_detects_response_format_errors() -> None:
    exc = _api_status_error("response_format is not supported for this model")
    assert _json_mode_unsupported(exc)
    assert not _temperature_unsupported(exc)


def test_chat_completion_retries_without_temperature() -> None:
    provider = OpenAICompatProvider(
        LLMConfig(
            provider=LLMProvider.OPENAI_COMPAT,
            base_url="[REDACTED]",
            model="gpt-5-reasoning-example",
        ),
        api_key="test-key",
    )
    calls: list[dict[str, object]] = []

    def fake_create(**kwargs: object) -> SimpleNamespace:
        calls.append(dict(kwargs))
        if "temperature" in kwargs:
            raise _api_status_error(
                "Unsupported value: 'temperature' does not support 0.2 with this model. "
                "Only the default (1) value is supported."
            )
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok": true}'))]
        )

    provider._client = MagicMock()
    provider._client.chat.completions.create = fake_create

    content = provider.chat_completion_multimodal(
        [{"role": "user", "content": "hello"}],
        temperature=0.2,
        json_mode=True,
    )

    assert content == '{"ok": true}'
    assert len(calls) == 2
    assert "temperature" in calls[0]
    assert "temperature" not in calls[1]


def test_chat_completion_retries_without_json_mode_then_temperature() -> None:
    provider = OpenAICompatProvider(
        LLMConfig(
            provider=LLMProvider.OPENAI_COMPAT,
            base_url="[REDACTED]",
            model="strict-model",
        ),
        api_key="test-key",
    )
    calls: list[dict[str, object]] = []

    def fake_create(**kwargs: object) -> SimpleNamespace:
        calls.append(dict(kwargs))
        if kwargs.get("response_format"):
            raise _api_status_error("response_format is not supported")
        if "temperature" in kwargs:
            raise _api_status_error(
                "Unsupported value: 'temperature' does not support 0.2 with this model."
            )
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok": true}'))]
        )

    provider._client = MagicMock()
    provider._client.chat.completions.create = fake_create

    content = provider.chat_completion_multimodal(
        [{"role": "user", "content": "hello"}],
        temperature=0.2,
        json_mode=True,
    )

    assert content == '{"ok": true}'
    assert len(calls) == 3
    assert calls[0].get("response_format") is not None
    assert calls[1].get("response_format") is None
    assert "temperature" in calls[1]
    assert calls[2].get("response_format") is None
    assert "temperature" not in calls[2]
