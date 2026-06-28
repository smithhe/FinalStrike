"""Structured computer-use actions from the vision LLM."""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

_JSON_FENCE_RE = re.compile(
    r"```(?:json)?\s*(\{.*?\})\s*```",
    re.DOTALL | re.IGNORECASE,
)

_ACTION_FIELD_NAMES = frozenset(
    {
        "type",
        "url",
        "x",
        "y",
        "text",
        "combo",
        "direction",
        "amount",
        "seconds",
        "title",
        "success",
        "message",
    }
)


class ActionPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: Literal[
        "launch",
        "click",
        "type",
        "key",
        "scroll",
        "wait",
        "focus_window",
        "done",
    ]
    url: str | None = None
    x: int | None = None
    y: int | None = None
    text: str | None = None
    combo: str | None = None
    direction: Literal["up", "down", "left", "right"] | None = None
    amount: int | None = None
    seconds: float | None = None
    title: str | None = None
    success: bool | None = None
    message: str | None = None

    @model_validator(mode="after")
    def _validate_required_fields(self) -> ActionPayload:
        required: dict[str, tuple[str, ...]] = {
            "launch": ("url",),
            "click": ("x", "y"),
            "type": ("text",),
            "key": ("combo",),
            "scroll": ("direction",),
            "wait": ("seconds",),
            "focus_window": ("title",),
            "done": ("success",),
        }
        fields = required.get(self.type, ())
        missing = [name for name in fields if getattr(self, name) is None]
        if missing:
            raise ValueError(
                f"action type {self.type!r} requires field(s): {', '.join(missing)}"
            )
        return self


class ComputerActionResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    thought: str = ""
    action: ActionPayload


_COORDINATE_ALIASES = (
    "coordinates",
    "coordinate",
    "position",
    "point",
    "coords",
    "coord",
    "xy",
)


def _as_int(value: Any) -> int:
    if isinstance(value, bool):
        raise TypeError("bool is not a valid coordinate")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(round(value))
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    raise TypeError(f"expected numeric coordinate, got {type(value).__name__}")


def _pair_from_sequence(values: Any) -> tuple[int, int] | None:
    if not isinstance(values, (list, tuple)) or len(values) < 2:
        return None
    return _as_int(values[0]), _as_int(values[1])


def _coerce_action_dict(action: dict[str, Any]) -> dict[str, Any]:
    """Normalize common coordinate shapes models emit for click actions."""
    if action.get("type") != "click":
        return action

    coerced = dict(action)

    x_val = coerced.get("x")
    if isinstance(x_val, (list, tuple)) and coerced.get("y") is None:
        pair = _pair_from_sequence(x_val)
        if pair is not None:
            coerced["x"], coerced["y"] = pair

    for key in _COORDINATE_ALIASES:
        if key not in coerced:
            continue
        alias = coerced.pop(key)
        if coerced.get("x") is not None and coerced.get("y") is not None:
            continue
        if isinstance(alias, dict):
            if alias.get("x") is not None and alias.get("y") is not None:
                coerced.setdefault("x", _as_int(alias["x"]))
                coerced.setdefault("y", _as_int(alias["y"]))
            continue
        pair = _pair_from_sequence(alias)
        if pair is not None:
            coerced.setdefault("x", pair[0])
            coerced.setdefault("y", pair[1])

    for axis in ("x", "y"):
        val = coerced.get(axis)
        if isinstance(val, str):
            coerced[axis] = _as_int(val)

    return coerced


def normalize_computer_action_response(data: dict[str, Any]) -> dict[str, Any]:
    """Coerce common LLM response shapes into ``{thought, action}``."""
    if isinstance(data.get("action"), dict):
        return {
            **data,
            "action": _coerce_action_dict(data["action"]),
        }
    if "type" in data:
        action = {key: data[key] for key in _ACTION_FIELD_NAMES if key in data}
        return {
            "thought": data.get("thought", ""),
            "action": _coerce_action_dict(action),
        }
    return data


def parse_action_response(raw: str) -> ComputerActionResponse:
    """Parse and validate LLM JSON output for a single action step."""
    try:
        payload = normalize_computer_action_response(extract_json_object(raw))
        return ComputerActionResponse.model_validate(payload)
    except (json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise ValueError(f"invalid computer-use action JSON: {exc}") from exc


def action_summary(action: ActionPayload) -> str:
    """Human-readable action label for logs and RunResult steps."""
    if action.type == "launch":
        return f"launch({action.url})"
    if action.type == "click":
        return f"click({action.x}, {action.y})"
    if action.type == "type":
        text = action.text or ""
        preview = text if len(text) <= 40 else f"{text[:37]}..."
        return f"type({preview!r})"
    if action.type == "key":
        return f"key({action.combo})"
    if action.type == "scroll":
        return f"scroll({action.direction}, {action.amount})"
    if action.type == "wait":
        return f"wait({action.seconds}s)"
    if action.type == "focus_window":
        return f"focus_window({action.title!r})"
    if action.type == "done":
        return f"done(success={action.success})"
    return action.type


def extract_json_object(raw: str) -> dict[str, Any]:
    """Extract a JSON object from raw LLM text (tolerates markdown fences)."""
    text = raw.strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        match = _JSON_FENCE_RE.search(text)
        if match is not None:
            parsed = json.loads(match.group(1))
        else:
            start = text.find("{")
            if start < 0:
                raise ValueError("response does not contain a JSON object") from None
            parsed = json.loads(text[start:])

    if not isinstance(parsed, dict):
        raise ValueError("expected JSON object")
    return parsed
