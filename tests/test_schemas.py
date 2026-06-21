"""Regression tests for committed JSON schemas."""

from __future__ import annotations

import json
from pathlib import Path

from finalstrike.config.export_schemas import export_schemas

SCHEMAS_DIR = Path(__file__).resolve().parents[1] / "schemas"


def test_exported_schemas_match_committed(tmp_path: Path) -> None:
    written = export_schemas(tmp_path)

    for filename, exported_path in written.items():
        committed_path = SCHEMAS_DIR / filename
        assert committed_path.is_file(), f"Missing committed schema: {filename}"
        exported = json.loads(exported_path.read_text(encoding="utf-8"))
        committed = json.loads(committed_path.read_text(encoding="utf-8"))
        assert exported == committed, f"Schema drift in {filename}; re-run export_schemas"
