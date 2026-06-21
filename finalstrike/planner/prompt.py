"""Prompt templates for the LLM test planner."""

from __future__ import annotations

import hashlib
import json

import yaml

from finalstrike.config.context import RepoContext
from finalstrike.config.models import VerificationPlan


PROMPT_TEMPLATE_VERSION = "1"

SYSTEM_PROMPT = """You are FinalStrike's verification planner.

Given acceptance criteria and repository context, produce a structured
VerificationPlan as JSON. Map each acceptance criterion to one or more
scenarios with concrete steps across these layers:

- terminal: shell commands (prefer commands from finalstrike.yaml tests section)
- api: HTTP checks with method, path, and expect.status (plus json_paths/headers when useful)
- ui: natural-language instructions for computer-use verification

Rules:
- Every scenario must have a unique id (e.g. ac-1, ac-2) and source quoting the criterion.
- Use relative API paths (e.g. /health) — base_url comes from config.
- Include a gaps array for criteria that cannot be automated (missing services, auth flows, etc.).
- Do not invent secrets or credentials.
- Return ONLY valid JSON matching the VerificationPlan schema — no markdown fences or commentary.
"""


def planner_prompt_version() -> str:
    """Stable hash for cassette invalidation when planner prompts change."""
    payload = f"{PROMPT_TEMPLATE_VERSION}\n{SYSTEM_PROMPT}"
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def verification_plan_schema_json() -> str:
    """JSON Schema string for the planner prompt."""
    return json.dumps(VerificationPlan.model_json_schema(), indent=2)


def build_planner_messages(
    context: RepoContext,
    *,
    validation_error: str | None = None,
) -> list[tuple[str, str]]:
    """Return (role, content) message pairs for the LLM."""
    config_yaml = yaml.safe_dump(
        context.config.model_dump(mode="json"),
        sort_keys=False,
    ).rstrip()
    planner_block = context.planner_context_block() or "(empty)"

    user_sections = [
        "## finalstrike.yaml\n",
        "```yaml",
        config_yaml,
        "```",
        "",
        "## Repository context",
        planner_block,
        "",
        "## VerificationPlan JSON Schema",
        "```json",
        verification_plan_schema_json(),
        "```",
        "",
        "Produce a VerificationPlan JSON object that covers every acceptance criterion.",
    ]

    if validation_error:
        user_sections.extend(
            [
                "",
                "## Previous attempt failed validation",
                validation_error,
                "",
                "Fix the JSON and return a valid VerificationPlan only.",
            ]
        )

    return [
        ("system", SYSTEM_PROMPT),
        ("user", "\n".join(user_sections)),
    ]
