"""Export JSON schemas from Pydantic models to schemas/."""

from __future__ import annotations

import json
from pathlib import Path

from finalstrike.config.models import FinalStrikeConfig, RunResult, VerificationPlan


def export_schemas(output_dir: Path | None = None) -> dict[str, Path]:
    """Write JSON Schema files for FinalStrikeConfig and VerificationPlan."""
    if output_dir is None:
        output_dir = Path(__file__).resolve().parents[2] / "schemas"
    output_dir.mkdir(parents=True, exist_ok=True)

    exports = {
        "finalstrike.schema.json": FinalStrikeConfig.model_json_schema(),
        "verification_plan.schema.json": VerificationPlan.model_json_schema(),
        "run_result.schema.json": RunResult.model_json_schema(),
    }

    written: dict[str, Path] = {}
    for filename, schema in exports.items():
        path = output_dir / filename
        path.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
        written[filename] = path

    return written


def main() -> None:
    written = export_schemas()
    for name, path in written.items():
        print(f"Wrote {path}")


if __name__ == "__main__":
    main()
