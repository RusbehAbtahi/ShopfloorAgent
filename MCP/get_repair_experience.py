"""Return raw historical repair experience for one MES error type.

This module reads repaired incidents from the MES SQLite database and returns
their stored repair comments without summarization or interpretation.

Main classes:
    GetRepairExperienceTool:
        Retrieves repaired cases for exactly one error ID.

Main methods:
    execute():
        Returns raw repair records filtered by optional time and line criteria.

Important notes:
    This module never asks questions or invokes an LLM. Presentation and any
    optional summarization belong to the future ProductionAgent client.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sqlite3
from typing import Any

from mcp_tool_instructions import load_mcp_tool_instructions


DEFAULT_DATA_DIR = Path(__file__).resolve().parents[1] / "MES" / "data"
VALID_LINE_IDS = frozenset({1, 2, 3, 4})


TOOL_NAME = 'get_repair_experience'
TOOL_TITLE = 'Shopfloor Repair Experience'
_INSTRUCTIONS = load_mcp_tool_instructions('custom_get_repair_experience.json')
TOOL_DESCRIPTION = _INSTRUCTIONS.tool_description
SERVER_INSTRUCTIONS = _INSTRUCTIONS.server_instruction

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "error_id": {"type": "string", "minLength": 1, "description": _INSTRUCTIONS.field_descriptions["error_id"]},
        "date_from": {"type": "string", "minLength": 1, "description": _INSTRUCTIONS.field_descriptions["date_from"]},
        "date_to": {"type": "string", "minLength": 1, "description": _INSTRUCTIONS.field_descriptions["date_to"]},
        "line_ids": {"type": "array", "items": {"type": "integer", "enum": [1, 2, 3, 4]}, "maxItems": 4, "uniqueItems": True, "description": _INSTRUCTIONS.field_descriptions["line_ids"]},
    },
    "required": ["error_id"],
    "additionalProperties": False,
}

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {"experiences": {"type": "array", "items": {"type": "object"}}},
    "required": ["experiences"],
    "additionalProperties": False,
}


class GetRepairExperienceTool:
    """Read raw repair comments from repaired historical incidents."""

    def __init__(self, data_dir: Path | None = None) -> None:
        self.data_dir = Path(data_dir or DEFAULT_DATA_DIR)
        self.db_path = self.data_dir / "mes.sqlite"

    def execute(
        self,
        error_id: str,
        date_from: str | None = None,
        date_to: str | None = None,
        line_ids: list[int] | None = None,
    ) -> dict[str, Any]:
        """Return repaired historical cases for exactly one error type."""
        normalized_error_id = str(error_id).strip()
        if not normalized_error_id:
            raise ValueError("error_id is required")

        start, end = self._validate_dates(date_from, date_to)
        selected_lines = self._validate_line_ids(line_ids)

        query = (
            "SELECT incident_id, occurrence_time, line_id, repair_time, "
            "repair_comment FROM incidents "
            "WHERE status = 'REPAIRED' AND error_id = ?"
        )
        parameters: list[Any] = [normalized_error_id]

        if start is not None:
            query += " AND occurrence_time >= ?"
            parameters.append(_format_mes_datetime(start))
        if end is not None:
            query += " AND occurrence_time <= ?"
            parameters.append(_format_mes_datetime(end))
        if selected_lines:
            placeholders = ",".join("?" for _ in selected_lines)
            query += f" AND line_id IN ({placeholders})"
            parameters.extend(selected_lines)

        query += " ORDER BY occurrence_time DESC, id DESC"
        rows = self._fetch_rows(query, parameters)

        experiences = [
            {
                "incident_id": str(row["incident_id"]),
                "occurrence_time": str(row["occurrence_time"]),
                "line_id": int(row["line_id"]),
                "repair_time": str(row["repair_time"]),
                "repair_comment": (
                    "" if row["repair_comment"] is None
                    else str(row["repair_comment"])
                ),
            }
            for row in rows
        ]
        return {"experiences": experiences}

    def _validate_dates(
        self,
        date_from: str | None,
        date_to: str | None,
    ) -> tuple[datetime | None, datetime | None]:
        start = (
            _parse_mes_datetime(date_from, "date_from")
            if date_from is not None
            else None
        )
        end = (
            _parse_mes_datetime(date_to, "date_to")
            if date_to is not None
            else None
        )
        if start is not None and end is not None and end < start:
            raise ValueError("date_to must not be earlier than date_from")
        return start, end

    def _validate_line_ids(self, line_ids: list[int] | None) -> list[int]:
        if line_ids is None:
            return []

        selected_lines: list[int] = []
        for raw_line_id in line_ids:
            line_id = int(raw_line_id)
            if line_id not in VALID_LINE_IDS:
                raise ValueError("line_ids may contain only values 1 through 4")
            if line_id not in selected_lines:
                selected_lines.append(line_id)
        return selected_lines

    def _fetch_rows(
        self,
        query: str,
        parameters: list[Any],
    ) -> list[sqlite3.Row]:
        if not self.db_path.exists():
            return []

        uri = f"{self.db_path.resolve().as_uri()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=5)
        connection.row_factory = sqlite3.Row
        try:
            return connection.execute(query, parameters).fetchall()
        finally:
            connection.close()


def _parse_mes_datetime(value: str, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).strip())
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a valid ISO-8601 datetime") from exc
    if parsed.tzinfo is not None:
        raise ValueError(
            f"{field_name} must be timezone-naive like the MES simulated time"
        )
    return parsed


def _format_mes_datetime(value: datetime) -> str:
    return value.isoformat(timespec="milliseconds")


def tool_metadata() -> dict[str, Any]:
    """Build the read-only MCP descriptor for this Shopfloor tool."""
    return {
        "name": TOOL_NAME,
        "title": TOOL_TITLE,
        "description": TOOL_DESCRIPTION,
        "inputSchema": INPUT_SCHEMA,
        "outputSchema": OUTPUT_SCHEMA,
        "annotations": {
            "destructiveHint": False,
            "readOnlyHint": True,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    }
