"""Record/replay LLM cassettes for deterministic integration tests."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from finalstrike.config.context import RepoContext
from finalstrike.config.models import VerificationPlan
from finalstrike.planner.prompt import build_planner_messages, planner_prompt_version
from finalstrike.providers.openai_compat import ChatMessage, OpenAICompatProvider


class CassetteMismatchError(AssertionError):
    """Raised when a committed cassette no longer matches repo inputs."""


@dataclass(frozen=True)
class CassetteMeta:
    id: str
    phase: int
    component: str
    acceptance: str
    acceptance_sha256: str
    prompt_version: str
    messages_sha256: str
    recorded_with: dict[str, Any]
    attempts: int
    notes: str = ""


@dataclass(frozen=True)
class PlannerCassette:
    root: Path
    meta: CassetteMeta
    messages: list[dict[str, str]]
    responses: list[str]
    canonical_plan: dict[str, Any]


class ReplayCassetteProvider:
    """Replay committed LLM responses in order."""

    def __init__(self, responses: list[str]) -> None:
        if not responses:
            raise ValueError("cassette must contain at least one response")
        self._responses = list(responses)
        self.calls = 0

    def chat_completion(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.2,
        json_mode: bool = True,
    ) -> str:
        del messages, temperature, json_mode
        if self.calls >= len(self._responses):
            raise RuntimeError(
                f"cassette exhausted after {self.calls} call(s); "
                f"expected {len(self._responses)}"
            )
        response = self._responses[self.calls]
        self.calls += 1
        return response


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_text(path.read_text(encoding="utf-8"))


def recordings_root() -> Path:
    return Path(__file__).resolve().parents[1] / "llm_recordings"


def planner_cassette_dir(cassette_id: str) -> Path:
    return recordings_root() / "planner" / cassette_id


def serialize_messages(messages: list[tuple[str, str]]) -> list[dict[str, str]]:
    return [{"role": role, "content": content} for role, content in messages]


def messages_sha256(messages: list[dict[str, str]]) -> str:
    payload = json.dumps(messages, sort_keys=True, ensure_ascii=False)
    return sha256_text(payload)


def load_planner_cassette(cassette_id: str) -> PlannerCassette:
    root = planner_cassette_dir(cassette_id)
    meta_path = root / "meta.yaml"
    messages_path = root / "messages.json"
    responses_path = root / "responses.json"
    plan_path = root / "plan.canonical.json"

    for path in (meta_path, messages_path, responses_path, plan_path):
        if not path.is_file():
            raise FileNotFoundError(f"missing cassette file: {path}")

    meta_data = yaml.safe_load(meta_path.read_text(encoding="utf-8"))
    if not isinstance(meta_data, dict):
        raise ValueError(f"invalid cassette meta: {meta_path}")

    messages = json.loads(messages_path.read_text(encoding="utf-8"))
    responses = json.loads(responses_path.read_text(encoding="utf-8"))
    canonical_plan = json.loads(plan_path.read_text(encoding="utf-8"))

    if not isinstance(messages, list) or not isinstance(responses, list):
        raise ValueError(f"invalid cassette JSON in {root}")

    return PlannerCassette(
        root=root,
        meta=CassetteMeta(**meta_data),
        messages=messages,
        responses=responses,
        canonical_plan=canonical_plan,
    )


def assert_cassette_matches_context(
    cassette: PlannerCassette,
    context: RepoContext,
    *,
    acceptance_path: Path,
) -> None:
    """Fail fast when inputs drift from the committed recording."""
    if cassette.meta.prompt_version != planner_prompt_version():
        raise CassetteMismatchError(
            "planner prompt changed; refresh cassette "
            f"{cassette.meta.id!r} (expected prompt_version "
            f"{cassette.meta.prompt_version}, got {planner_prompt_version()})"
        )

    acceptance_sha = sha256_file(acceptance_path)
    if cassette.meta.acceptance_sha256 != acceptance_sha:
        raise CassetteMismatchError(
            f"acceptance file changed; refresh cassette {cassette.meta.id!r}"
        )

    built_messages = serialize_messages(build_planner_messages(context))
    built_sha = messages_sha256(built_messages)
    if cassette.meta.messages_sha256 != built_sha:
        raise CassetteMismatchError(
            "planner input messages changed; refresh cassette "
            f"{cassette.meta.id!r} (AGENTS.md, finalstrike.yaml, or schema drift)"
        )


def record_planner_cassette(
    cassette_id: str,
    context: RepoContext,
    *,
    acceptance_path: Path,
    provider: OpenAICompatProvider | None = None,
    notes: str = "",
) -> PlannerCassette:
    """Record a planner cassette from a live LLM call (manual refresh workflow)."""
    if context.acceptance is None:
        raise ValueError("acceptance criteria required to record cassette")

    llm = provider or OpenAICompatProvider.from_context(
        context.config.llm,
        context.secrets,
    )
    messages = build_planner_messages(context)
    serialized = serialize_messages(messages)
    chat_messages = [ChatMessage(role=m["role"], content=m["content"]) for m in serialized]
    raw = llm.chat_completion(chat_messages, temperature=0.2, json_mode=True)
    plan = VerificationPlan.model_validate_json(raw)

    root = planner_cassette_dir(cassette_id)
    root.mkdir(parents=True, exist_ok=True)

    meta = CassetteMeta(
        id=cassette_id,
        phase=5,
        component="planner",
        acceptance=str(acceptance_path.relative_to(Path.cwd())),
        acceptance_sha256=sha256_file(acceptance_path),
        prompt_version=planner_prompt_version(),
        messages_sha256=messages_sha256(serialized),
        recorded_with={
            "base_url": context.config.llm.base_url,
            "model": context.config.llm.model,
            "temperature": 0.2,
        },
        attempts=1,
        notes=notes,
    )

    (root / "meta.yaml").write_text(
        yaml.safe_dump(meta.__dict__, sort_keys=False),
        encoding="utf-8",
    )
    (root / "messages.json").write_text(
        json.dumps(serialized, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (root / "responses.json").write_text(
        json.dumps([raw], indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    canonical = plan.model_dump(mode="json")
    (root / "plan.canonical.json").write_text(
        json.dumps(canonical, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    return load_planner_cassette(cassette_id)


def should_record_llm() -> bool:
    return os.environ.get("FINALSTRIKE_RECORD_LLM", "").strip() in {
        "1",
        "true",
        "yes",
    }


DEFAULT_SMOKE_CASSETTE_ID = "smoke-v1"
