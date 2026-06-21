"""Load VerificationPlan JSON for run orchestration."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from finalstrike.config.models import VerificationPlan


def load_verification_plan(path: Path) -> VerificationPlan:
    """Load and validate a VerificationPlan JSON file."""
    if not path.is_file():
        raise FileNotFoundError(f"Verification plan not found: {path}")
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    try:
        return VerificationPlan.model_validate(data)
    except ValidationError as exc:
        raise ValueError(f"Invalid verification plan: {exc}") from exc
