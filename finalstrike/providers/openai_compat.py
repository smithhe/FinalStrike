"""OpenAI-compatible LLM adapter (Phase 5)."""

from __future__ import annotations

import os
from dataclasses import dataclass

from openai import APIConnectionError, APIStatusError, OpenAI

from finalstrike.config.models import LLMConfig


class LLMProviderError(RuntimeError):
    """Raised when the LLM provider cannot complete a request."""


@dataclass(frozen=True)
class ChatMessage:
    role: str
    content: str


def resolve_api_key(secrets: dict[str, str], *, base_url: str) -> str:
    """Resolve API key from secrets vault or environment.

    Ollama and many local gateways accept any non-empty placeholder when no
    real key is configured.
    """
    for source in (secrets, os.environ):
        key = source.get("OPENAI_API_KEY")
        if key:
            return key
    if _is_local_gateway(base_url):
        return "ollama"
    raise LLMProviderError(
        "No OPENAI_API_KEY in secrets vault or environment. "
        "Add it to .finalstrike/secrets.env or export OPENAI_API_KEY."
    )


def _is_local_gateway(base_url: str) -> bool:
    lowered = base_url.lower()
    return "localhost" in lowered or "127.0.0.1" in lowered


class OpenAICompatProvider:
    """Thin wrapper around the OpenAI Python SDK with configurable base_url."""

    def __init__(
        self,
        config: LLMConfig,
        *,
        api_key: str,
        timeout: float = 120.0,
    ) -> None:
        self.config = config
        self.api_key = api_key
        self._client = OpenAI(
            base_url=config.base_url,
            api_key=api_key,
            timeout=timeout,
        )

    @classmethod
    def from_context(
        cls,
        config: LLMConfig,
        secrets: dict[str, str],
        *,
        timeout: float = 120.0,
    ) -> OpenAICompatProvider:
        api_key = resolve_api_key(secrets, base_url=config.base_url)
        return cls(config, api_key=api_key, timeout=timeout)

    def chat_completion(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.2,
        json_mode: bool = True,
    ) -> str:
        """Request a chat completion and return the assistant message text."""
        payload_messages = [
            {"role": message.role, "content": message.content} for message in messages
        ]
        kwargs: dict[str, object] = {
            "model": self.config.model,
            "messages": payload_messages,
            "temperature": temperature,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        try:
            response = self._create_completion(kwargs)
        except APIStatusError as exc:
            if json_mode and _json_mode_unsupported(exc):
                kwargs.pop("response_format", None)
                response = self._create_completion(kwargs)
            else:
                raise LLMProviderError(
                    f"LLM request failed ({exc.status_code}): {exc.message}"
                ) from exc
        except APIConnectionError as exc:
            raise LLMProviderError(
                f"Cannot reach LLM at {self.config.base_url}: {exc}"
            ) from exc

        content = response.choices[0].message.content
        if not content:
            raise LLMProviderError("LLM returned an empty response")
        return content

    def _create_completion(self, kwargs: dict[str, object]):
        return self._client.chat.completions.create(**kwargs)


def _json_mode_unsupported(exc: APIStatusError) -> bool:
    message = (exc.message or "").lower()
    return exc.status_code in {400, 404, 422} and (
        "response_format" in message
        or "json" in message
        or "unsupported" in message
    )
