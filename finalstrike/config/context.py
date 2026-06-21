"""Merged repository context for planner and orchestrator."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from finalstrike.config.acceptance import AcceptanceCriteria, load_acceptance
from finalstrike.config.agents import AgentsContext, load_agents
from finalstrike.config.environment import EnvironmentConfig, load_environment
from finalstrike.config.loader import load_config
from finalstrike.config.models import FinalStrikeConfig
from finalstrike.config.secrets import apply_to_environ, load_secrets, redact_secrets


class RepoContext(BaseModel):
    """Combined config and context snapshot for a target repo."""

    model_config = ConfigDict(extra="forbid")

    repo: Path
    config: FinalStrikeConfig
    agents: AgentsContext
    environment: EnvironmentConfig
    secrets: dict[str, str]
    secrets_warnings: list[str] = Field(default_factory=list)
    subprocess_env: dict[str, str] = Field(default_factory=dict)
    acceptance: AcceptanceCriteria | None = None

    def redacted_secrets(self) -> dict[str, str]:
        return redact_secrets(self.secrets)

    def planner_context_block(self) -> str:
        """Assemble planner-facing context using AGENTS.md context block."""
        blocks: list[str] = []

        agents_block = self.agents.to_context_block(repo=self.repo)
        if agents_block:
            blocks.append(agents_block.rstrip())

        if self.environment.present:
            env_lines = self.environment.summary_lines()
            blocks.append("## Environment\n" + "\n".join(env_lines))

        if self.acceptance is not None:
            blocks.append(
                "## Acceptance Criteria\n\n" + self.acceptance.content.rstrip()
            )

        return "\n\n".join(blocks)

    def format_dry_run(self) -> str:
        """Format merged context for plan --dry-run output."""
        sections: list[str] = []

        sections.append("# FinalStrike Plan Context (dry-run)\n")
        sections.append(f"**Repo:** `{self.repo}`\n")

        config_dict = self.config.model_dump(mode="json")
        sections.append("## finalstrike.yaml\n")
        sections.append("```yaml")
        sections.append(yaml.safe_dump(config_dict, sort_keys=False).rstrip())
        sections.append("```\n")

        sections.append("## Planner Context\n")
        planner_block = self.planner_context_block()
        sections.append(planner_block if planner_block else "(empty)")
        sections.append("")

        sections.append("## Environment (.cursor/environment.json)\n")
        for line in self.environment.summary_lines():
            sections.append(line)
        sections.append("")

        sections.append("## Secrets\n")
        redacted = self.redacted_secrets()
        if redacted:
            for key in sorted(redacted):
                sections.append(f"- {key}: ***")
        else:
            sections.append("(none loaded)")
        if self.secrets_warnings:
            sections.append("")
            sections.append("Warnings:")
            for warning in self.secrets_warnings:
                sections.append(f"- {warning}")
        sections.append("")

        sections.append("## Acceptance Criteria\n")
        if self.acceptance is not None:
            sections.append(f"**Source:** `{self.acceptance.source}`\n")
            sections.append(self.acceptance.content.rstrip())
            sections.append("")
        else:
            sections.append("(not provided)")

        return "\n".join(sections)


def load_repo_context(
    repo: Path,
    acceptance_path: Path | None = None,
    acceptance_stdin: bool = False,
    acceptance_content: str | None = None,
    inject_secrets: bool = True,
) -> RepoContext:
    """Load and merge all repo context sources.

    ``acceptance_content`` is used by tests/CLI when stdin has already been read.
    When ``inject_secrets`` is true, loaded secrets are merged into ``os.environ``.
    """
    repo = repo.resolve()
    config = load_config(repo)
    agents = load_agents(repo)
    environment = load_environment(repo)
    secrets, secrets_warnings = load_secrets(repo, config.secrets.file)
    subprocess_env = apply_to_environ(secrets)
    if inject_secrets and secrets:
        os.environ.update(secrets)

    acceptance: AcceptanceCriteria | None = None
    if acceptance_stdin:
        if acceptance_content is None:
            from finalstrike.config.acceptance import load_acceptance_from_stdin

            acceptance = load_acceptance_from_stdin()
        else:
            from finalstrike.config.acceptance import _validate_acceptance_content

            acceptance = _validate_acceptance_content(acceptance_content, "stdin")
    elif acceptance_path is not None:
        acceptance = load_acceptance(acceptance_path)

    return RepoContext(
        repo=repo,
        config=config,
        agents=agents,
        environment=environment,
        secrets=secrets,
        secrets_warnings=secrets_warnings,
        subprocess_env=subprocess_env,
        acceptance=acceptance,
    )
