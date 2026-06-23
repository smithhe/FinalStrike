"""Assess whether a repo's configured LLM endpoint is ready for live calls."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import httpx
from pydantic import ValidationError

from finalstrike.computer_use.config import resolve_computer_use_llm
from finalstrike.config.loader import load_config
from finalstrike.config.models import LLMConfig
from finalstrike.config.secrets import load_secrets
from finalstrike.providers.openai_compat import (
    LLMProviderError,
    OpenAICompatProvider,
    resolve_api_key,
)

# 1x1 red PNG — minimal payload for vision capability probes.
_PROBE_IMAGE_DATA_URL = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


@dataclass(frozen=True)
class LiveLLMStatus:
    ready: bool
    detail: str
    base_url: str | None = None
    model: str | None = None


@dataclass(frozen=True)
class VisionLLMStatus:
    ready: bool
    detail: str
    base_url: str | None = None
    model: str | None = None


def assess_live_llm(repo: Path) -> LiveLLMStatus:
    """Return whether ``finalstrike.yaml`` + secrets can reach the planner LLM."""
    llm, secrets, err = _load_repo_llm(repo, use_computer_use=False)
    if err is not None:
        return err
    assert llm is not None
    return _assess_llm_reachability(llm, secrets)


def assess_computer_use_llm(repo: Path) -> LiveLLMStatus:
    """Return whether the computer-use LLM endpoint is reachable."""
    llm, secrets, err = _load_repo_llm(repo, use_computer_use=True)
    if err is not None:
        return err
    assert llm is not None
    return _assess_llm_reachability(llm, secrets)


def assess_computer_use_vision(repo: Path) -> VisionLLMStatus:
    """Probe whether the computer-use LLM accepts multimodal (image) input."""
    llm, secrets, err = _load_repo_llm(repo, use_computer_use=True)
    if err is not None:
        return VisionLLMStatus(
            ready=False,
            detail=err.detail,
            base_url=err.base_url,
            model=err.model,
        )
    assert llm is not None

    reachability = _assess_llm_reachability(llm, secrets)
    if not reachability.ready:
        return VisionLLMStatus(
            ready=False,
            detail=reachability.detail,
            base_url=reachability.base_url,
            model=reachability.model,
        )

    try:
        provider = OpenAICompatProvider.from_context(llm, secrets, timeout=15.0)
        provider.chat_completion_multimodal(
            [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": 'Reply with JSON: {"ok": true}',
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": _PROBE_IMAGE_DATA_URL},
                        },
                    ],
                }
            ],
            json_mode=False,
        )
    except LLMProviderError as exc:
        message = str(exc).lower()
        if any(
            token in message
            for token in ("image", "vision", "multimodal", "image_url", "multi-modal")
        ):
            return VisionLLMStatus(
                ready=False,
                detail=f"Model does not accept image input: {exc}",
                base_url=llm.base_url,
                model=llm.model,
            )
        return VisionLLMStatus(
            ready=False,
            detail=str(exc),
            base_url=llm.base_url,
            model=llm.model,
        )

    return VisionLLMStatus(
        ready=True,
        detail=f"{llm.base_url} ({llm.model}) accepts image input",
        base_url=llm.base_url,
        model=llm.model,
    )


def _load_repo_llm(
    repo: Path,
    *,
    use_computer_use: bool,
) -> tuple[LLMConfig | None, dict[str, str], LiveLLMStatus | None]:
    repo = repo.resolve()
    try:
        base_config = load_config(repo)
    except (FileNotFoundError, ValueError, ValidationError) as exc:
        return None, {}, LiveLLMStatus(ready=False, detail=f"Cannot load config: {exc}")

    secrets, _ = load_secrets(repo, base_config.secrets.file)
    try:
        config = load_config(repo, secrets=secrets, environ=None)
    except (FileNotFoundError, ValueError, ValidationError) as exc:
        return None, {}, LiveLLMStatus(ready=False, detail=f"Cannot load config: {exc}")

    llm = resolve_computer_use_llm(config) if use_computer_use else config.llm
    return llm, secrets, None


def _assess_llm_reachability(
    llm: LLMConfig,
    secrets: dict[str, str],
) -> LiveLLMStatus:
    try:
        api_key = resolve_api_key(secrets, base_url=llm.base_url)
    except LLMProviderError as exc:
        return LiveLLMStatus(
            ready=False,
            detail=str(exc),
            base_url=llm.base_url,
            model=llm.model,
        )

    models_url = f"{llm.base_url.rstrip('/')}/models"
    try:
        with httpx.Client(timeout=2.0) as client:
            response = client.get(
                models_url,
                headers={"Authorization": f"Bearer {api_key}"},
            )
    except httpx.HTTPError as exc:
        return LiveLLMStatus(
            ready=False,
            detail=f"Cannot reach {llm.base_url}: {exc}",
            base_url=llm.base_url,
            model=llm.model,
        )

    if response.status_code == 200:
        return LiveLLMStatus(
            ready=True,
            detail=f"{llm.base_url} ({llm.model}) reachable",
            base_url=llm.base_url,
            model=llm.model,
        )
    if response.status_code == 401:
        return LiveLLMStatus(
            ready=False,
            detail=f"OPENAI_API_KEY rejected by {llm.base_url}",
            base_url=llm.base_url,
            model=llm.model,
        )
    return LiveLLMStatus(
        ready=False,
        detail=f"{models_url} returned HTTP {response.status_code}",
        base_url=llm.base_url,
        model=llm.model,
    )
