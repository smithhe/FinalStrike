"""Prompt templates for the computer-use vision/action loop."""

from __future__ import annotations

import hashlib
import json

from finalstrike.computer_use.actions import ActionPayload, ComputerActionResponse


PROMPT_TEMPLATE_VERSION = "1"

SYSTEM_PROMPT = """You are FinalStrike's computer-use agent on a Linux desktop VM.

You receive a desktop screenshot, a lightweight accessibility summary, and a
verification instruction. Choose exactly ONE next action as JSON.

Return ONLY a JSON object with:
- thought: brief reasoning
- action: object with type and required fields

Allowed action types:
- launch: { "type": "launch", "url": "https://..." }
- click: { "type": "click", "x": 100, "y": 200 }
- type: { "type": "type", "text": "hello" }
- key: { "type": "key", "combo": "Return" }
- scroll: { "type": "scroll", "direction": "down", "amount": 3 }
- wait: { "type": "wait", "seconds": 2 }
- focus_window: { "type": "focus_window", "title": "partial window title" }
- done: { "type": "done", "success": true, "message": "what was verified" }

Rules:
- Use launch when a browser URL must be opened.
- Use done only when the instruction is satisfied or cannot be completed.
- Prefer focus_window before typing when a specific window is needed.
- Coordinates are pixels on the full desktop screenshot.
- Chrome/Chromium may show the hostname (e.g. "localhost") as the tab title until
  the page finishes loading; use wait and check visible_windows before done.
- visible_windows lists WM-reported titles; prefer it when verifying page titles.
- Return valid JSON only — no markdown fences.
"""


def action_prompt_version() -> str:
    payload = f"{PROMPT_TEMPLATE_VERSION}\n{SYSTEM_PROMPT}"
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def action_schema_json() -> str:
    schema = ComputerActionResponse.model_json_schema()
    return json.dumps(schema, indent=2)


def build_action_messages(
    *,
    instruction: str,
    screenshot_data_url: str,
    a11y_summary: str,
    history: list[str],
    validation_error: str | None = None,
    ui_base_url: str | None = None,
    smoke_route: str = "/",
) -> list[dict[str, object]]:
    """Build multimodal chat messages for the vision LLM."""
    from finalstrike.computer_use.urls import canonical_ui_url

    history_block = "\n".join(history[-8:]) if history else "(none)"
    text_sections = [
        "## Instruction",
        instruction,
    ]
    if ui_base_url is not None:
        canonical = canonical_ui_url(base_url=ui_base_url, smoke_route=smoke_route)
        text_sections.extend(
            [
                "",
                "## Configured UI",
                f"base_url: {ui_base_url}",
                f"smoke_route: {smoke_route}",
                f"canonical_url: {canonical}",
                "Use launch with a URL on this origin when opening the app.",
            ]
        )
    text_sections.extend(
        [
        "",
        "## Accessibility",
        a11y_summary,
        "",
        "## Recent actions",
        history_block,
        "",
        "## Action JSON Schema",
        "```json",
        action_schema_json(),
        "```",
        "",
        "For click actions, set separate integer fields x and y (not a coordinate array).",
        "",
        "Choose the next action JSON object.",
        ]
    )
    if validation_error:
        text_sections.extend(
            [
                "",
                "## Previous attempt failed validation",
                validation_error,
                "",
                "Fix the JSON and return a valid action only.",
            ]
        )

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "\n".join(text_sections)},
                {"type": "image_url", "image_url": {"url": screenshot_data_url}},
            ],
        },
    ]


def summarize_completed_action(action: ActionPayload) -> str:
    if action.type == "done":
        return f"done(success={action.success}): {action.message or ''}"
    return action.type
