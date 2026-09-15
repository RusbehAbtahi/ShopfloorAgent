"""Return deterministic troubleshooting guidance from the MES error notebook.

This module reads only the existing static error_notebook.json. If no error IDs
are supplied, it derives the distinct error types of currently OPEN incidents.

Main classes:
    GetResolutionInstructionsTool:
        Resolves one or more error IDs to approved troubleshooting guidance.

Main methods:
    execute():
        Returns notebook guidance for explicit or currently open error types.

Important notes:
    The tool performs no historical search, summarization, root-cause generation,
    or repair action. Missing matches produce an empty valid result.
"""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from typing import Any


DEFAULT_DATA_DIR = Path(__file__).resolve().parents[1] / "MES" / "data"


class GetResolutionInstructionsTool:
    """Read approved troubleshooting instructions from the MES notebook."""

    def __init__(self, data_dir: Path | None = None) -> None:
        self.data_dir = Path(data_dir or DEFAULT_DATA_DIR)
        self.db_path = self.data_dir / "mes.sqlite"
        self.notebook_path = self.data_dir / "error_notebook.json"

    def execute(
        self,
        error_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Return deterministic notebook entries for the requested errors."""
        selected_error_ids = (
            _normalize_error_ids(error_ids)
            if error_ids is not None
            else self._open_error_ids()
        )
        notebook_errors = self._load_notebook_errors()

        instructions = []
        for error_id in selected_error_ids:
            entry = notebook_errors.get(error_id)
            if entry is None:
                continue
            instructions.append(
                {
                    "error_id": error_id,
                    "meaning": entry.get("meaning"),
                    "likely_causes": list(entry.get("likely_causes", [])),
                    "recommended_actions": list(
                        entry.get("recommended_actions", [])
                    ),
                    "repair_confirmation": entry.get("repair_confirmation"),
                }
            )

        return {"instructions": instructions}

    def _open_error_ids(self) -> list[str]:
        if not self.db_path.exists():
            return []

        uri = f"{self.db_path.resolve().as_uri()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=5)
        connection.row_factory = sqlite3.Row
        try:
            rows = connection.execute(
                """
                SELECT error_id
                FROM incidents
                WHERE status = 'OPEN'
                ORDER BY occurrence_time DESC, id DESC
                """
            ).fetchall()
        finally:
            connection.close()

        error_ids: list[str] = []
        for row in rows:
            error_id = str(row["error_id"])
            if error_id not in error_ids:
                error_ids.append(error_id)
        return error_ids

    def _load_notebook_errors(self) -> dict[str, dict[str, Any]]:
        if not self.notebook_path.exists():
            return {}

        try:
            notebook = json.loads(
                self.notebook_path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("MES error notebook is not valid JSON") from exc

        errors = notebook.get("errors", {})
        if not isinstance(errors, dict):
            raise ValueError("MES error notebook has an invalid errors section")
        return errors


def _normalize_error_ids(error_ids: list[str]) -> list[str]:
    normalized: list[str] = []
    for raw_error_id in error_ids:
        error_id = str(raw_error_id).strip()
        if not error_id:
            raise ValueError("error_ids must not contain empty values")
        if error_id not in normalized:
            normalized.append(error_id)
    return normalized
