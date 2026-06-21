"""LLM test planner: acceptance criteria → VerificationPlan."""

from __future__ import annotations

import json
import re
from typing import Protocol

from pydantic import ValidationError

from finalstrike.config.context import RepoContext
from finalstrike.config.models import VerificationPlan
from finalstrike.planner.prompt import build_planner_messages
from finalstrike.providers.openai_compat import ChatMessage, OpenAICompatProvider


class LLMClient(Protocol):
    def chat_completion(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.2,
        json_mode: bool = True,
    ) -> str: ...


_JSON_FENCE_RE = re.compile(
    r"```(?:json)?\s*(\{.*?\})\s*```",
    re.DOTALL | re.IGNORECASE,
)


def extract_json_object(text: str) -> dict[str, object]:
    """Parse JSON from raw LLM output, tolerating markdown fences."""
    stripped = text.strip()
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        match = _JSON_FENCE_RE.search(stripped)
        if match is None:
            brace = stripped.find("{")
            if brace < 0:
                raise ValueError("Response does not contain JSON object") from None
            data = json.loads(stripped[brace:])
        else:
            data = json.loads(match.group(1))

    if not isinstance(data, dict):
        raise ValueError("VerificationPlan must be a JSON object")
    return data


def validate_plan_payload(data: dict[str, object]) -> VerificationPlan:
    try:
        return VerificationPlan.model_validate(data)
    except ValidationError as exc:
        raise ValueError(f"Invalid VerificationPlan: {exc}") from exc


def generate_verification_plan(
    context: RepoContext,
    *,
    provider: LLMClient | None = None,
    max_retries: int = 3,
) -> VerificationPlan:
    """Call the LLM planner and return a validated VerificationPlan."""
    if context.acceptance is None:
        raise ValueError("Acceptance criteria are required for planning")

    llm = provider or OpenAICompatProvider.from_context(
        context.config.llm,
        context.secrets,
    )

    validation_error: str | None = None
    last_error: str | None = None

    for attempt in range(max_retries):
        messages = [
            ChatMessage(role=role, content=content)
            for role, content in build_planner_messages(
                context,
                validation_error=validation_error,
            )
        ]
        raw = llm.chat_completion(messages, temperature=0.2, json_mode=True)
        try:
            payload = extract_json_object(raw)
            return validate_plan_payload(payload)
        except (ValueError, json.JSONDecodeError) as exc:
            last_error = str(exc)
            validation_error = last_error
            if attempt + 1 >= max_retries:
                break

    raise ValueError(
        f"Planner failed after {max_retries} attempts: {last_error}"
    ) from None
