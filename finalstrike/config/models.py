"""Pydantic models for finalstrike.yaml, VerificationPlan, and RunResult."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


# --- finalstrike.yaml (section 4.1) ---


class ProjectConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str


class LLMProvider(str, Enum):
    OPENAI_COMPAT = "openai_compat"


class LLMConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: LLMProvider = LLMProvider.OPENAI_COMPAT
    base_url: str
    model: str


class CommandConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    run: str
    optional: bool = False


class BuildConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    commands: list[CommandConfig] = Field(default_factory=list)


class TestsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    commands: list[CommandConfig] = Field(default_factory=list)


class HealthCheckConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: str = "GET"
    path: str
    expect_status: int = 200


class APIConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_url: str
    health: list[HealthCheckConfig] = Field(default_factory=list)


class UIConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_url: str
    browser: str = "chromium"
    smoke_route: str = "/"


class SecretsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file: str = ".finalstrike/secrets.env"


class EvidenceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    video: bool = True
    screenshots: bool = True
    output_dir: str = ".finalstrike/runs"


class SlackConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bot_token_secret: str
    channel_id: str


class PolicyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fail_fast: bool = False
    max_test_retries: int = 0
    max_ui_steps: int = 40
    max_ui_retries: int = 4


class FinalStrikeConfig(BaseModel):
    """Root config model for finalstrike.yaml in a target repo."""

    model_config = ConfigDict(extra="forbid")

    version: Literal["1"] = "1"
    project: ProjectConfig
    llm: LLMConfig
    build: BuildConfig = Field(default_factory=BuildConfig)
    tests: TestsConfig = Field(default_factory=TestsConfig)
    api: APIConfig | None = None
    ui: UIConfig | None = None
    secrets: SecretsConfig = Field(default_factory=SecretsConfig)
    evidence: EvidenceConfig = Field(default_factory=EvidenceConfig)
    slack: SlackConfig | None = None
    policy: PolicyConfig = Field(default_factory=PolicyConfig)


# --- VerificationPlan (section 5.1) ---


class TerminalPlanStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command: str
    reason: str


class APIExpectation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: int
    json_paths: dict[str, Any] | None = None
    headers: dict[str, str] | None = None


class APIPlanStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: str
    path: str
    expect: APIExpectation
    body: Any | None = None
    headers: dict[str, str] | None = None


class UIPlanStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instruction: str


class ScenarioLayers(BaseModel):
    model_config = ConfigDict(extra="forbid")

    terminal: list[TerminalPlanStep] = Field(default_factory=list)
    api: list[APIPlanStep] = Field(default_factory=list)
    ui: list[UIPlanStep] = Field(default_factory=list)


class Scenario(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    source: str
    layers: ScenarioLayers


class PlanGap(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item: str
    reason: str


class VerificationPlan(BaseModel):
    """Structured test plan produced by the LLM planner."""

    model_config = ConfigDict(extra="forbid")

    scenarios: list[Scenario] = Field(default_factory=list)
    gaps: list[PlanGap] = Field(default_factory=list)


# --- RunResult (section 5.2) ---


class RunStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    PARTIAL = "partial"


class LayerStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"


class EnvLayerResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: LayerStatus
    duration_ms: int
    logs: str = ""


class BuildCommandResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    status: LayerStatus
    exit_code: int
    duration_ms: int
    stdout: str = ""
    stderr: str = ""


class BuildLayerResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: LayerStatus
    commands: list[BuildCommandResult] = Field(default_factory=list)


class TerminalCommandResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    status: LayerStatus
    exit_code: int
    duration_ms: int
    total_passed: int = 0
    total_failed: int = 0
    stdout: str = ""
    stderr: str = ""


class TerminalLayerResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: LayerStatus
    commands: list[TerminalCommandResult] = Field(default_factory=list)
    total_passed: int = 0
    total_failed: int = 0


class APICheckResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: str
    path: str
    status: LayerStatus
    expected_status: int | None = None
    actual_status: int | None = None
    duration_ms: int = 0
    response_body: str = ""
    error: str | None = None


class APILayerResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: LayerStatus
    checks: list[APICheckResult] = Field(default_factory=list)


class UIScenarioResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    status: LayerStatus
    steps_completed: int = 0


class UIStepResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_index: int
    action: str
    screenshot: str | None = None
    status: LayerStatus


class UILayerResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: LayerStatus
    scenarios: list[UIScenarioResult] = Field(default_factory=list)
    steps: list[UIStepResult] = Field(default_factory=list)


class RunLayers(BaseModel):
    model_config = ConfigDict(extra="forbid")

    env: EnvLayerResult | None = None
    build: BuildLayerResult | None = None
    terminal: TerminalLayerResult | None = None
    api: APILayerResult | None = None
    ui: UILayerResult | None = None


class RunArtifacts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    video: str | None = None
    screenshots: list[str] = Field(default_factory=list)
    html_report: str | None = None


class RunResult(BaseModel):
    """Canonical evidence bundle output for a verification run."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    repo: str
    branch: str | None = None
    status: RunStatus
    layers: RunLayers = Field(default_factory=RunLayers)
    artifacts: RunArtifacts = Field(default_factory=RunArtifacts)
    gaps: list[PlanGap] = Field(default_factory=list)
