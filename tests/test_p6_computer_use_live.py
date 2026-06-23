"""Unit tests for computer-use LLM assessment helpers."""

from __future__ import annotations

from finalstrike.providers.live import assess_computer_use_vision
from finalstrike.providers.openai_compat import LLMProviderError


def test_vision_probe_does_not_treat_generic_errors_as_no_vision(
    monkeypatch,
) -> None:
    class _FakeProvider:
        @classmethod
        def from_context(cls, *args, **kwargs):  # type: ignore[no-untyped-def]
            del args, kwargs
            return cls()

        def chat_completion_multimodal(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            del args, kwargs
            raise LLMProviderError("unsupported model foo")

    monkeypatch.setattr(
        "finalstrike.providers.live._load_repo_llm",
        lambda repo, use_computer_use=False: (
            type("LLM", (), {"base_url": "http://x", "model": "m"})(),
            {},
            None,
        ),
    )
    monkeypatch.setattr(
        "finalstrike.providers.live._assess_llm_reachability",
        lambda llm, secrets: type(
            "Status",
            (),
            {"ready": True, "detail": "ok", "base_url": "http://x", "model": "m"},
        )(),
    )
    monkeypatch.setattr(
        "finalstrike.providers.live.OpenAICompatProvider",
        _FakeProvider,
    )

    status = assess_computer_use_vision(type("Path", (), {})())
    assert status.ready is False
    assert "does not accept image input" not in status.detail
    assert "unsupported model foo" in status.detail
