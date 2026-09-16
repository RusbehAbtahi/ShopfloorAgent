"""Query deterministic MES incident history with optional filters.

This module reads structured incident facts from the existing MES SQLite
database. It never loads sensor snapshots, repair guidance, production impact,
or repair-experience summaries.

Main classes:
    ListPriorIncidentsTool:
        Filters and returns compact incident-history records.

Main methods:
    execute():
        Returns matching incidents newest first with client-facing status names.

Important notes:
    MES stores repaired incidents as REPAIRED. The MCP-facing contract maps that
    value to CLOSED without changing the MES database.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sqlite3
from typing import Any

from mcp_tool_instructions import load_mcp_tool_instructions


DEFAULT_DATA_DIR = Path(__file__).resolve().parents[1] / "MES" / "data"
VALID_LINE_IDS = frozenset({1, 2, 3, 4})


TOOL_NAME = 'list_prior_incidents'
TOOL_TITLE = 'Shopfloor Prior Incidents'
_INSTRUCTIONS = load_mcp_tool_instructions('custom_list_prior_incidents.json')
TOOL_DESCRIPTION = _INSTRUCTIONS.tool_description
SERVER_INSTRUCTIONS = _INSTRUCTIONS.server_instruction

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "date_from": {"type": "string", "minLength": 1, "description": _INSTRUCTIONS.field_descriptions["date_from"]},
        "date_to": {"type": "string", "minLength": 1, "description": _INSTRUCTIONS.field_descriptions["date_to"]},
        "line_ids": {"type": "array", "items": {"type": "integer", "enum": [1, 2, 3, 4]}, "maxItems": 4, "uniqueItems": True, "description": _INSTRUCTIONS.field_descriptions["line_ids"]},
        "station_ids": {"type": "array", "items": {"type": "string", "enum": ["Station 1", "Station 2", "Station 3"]}, "maxItems": 3, "uniqueItems": True, "description": _INSTRUCTIONS.field_descriptions["station_ids"]},
        "error_ids": {"type": "array", "items": {"type": "string", "minLength": 1}, "uniqueItems": True, "description": _INSTRUCTIONS.field_descriptions["error_ids"]},
    },
    "additionalProperties": False,
}

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {"incidents": {"type": "array", "items": {"type": "object"}}},
    "required": ["incidents"],
    "additionalProperties": False,
}


class ListPriorIncidentsTool:
    """Read compact incident-history records from the MES SQLite database."""

    def __init__(self, data_dir: Path | None = None) -> None:
        self.data_dir = Path(data_dir or DEFAULT_DATA_DIR)
        self.db_path = self.data_dir / "mes.sqlite"

    def execute(
        self,
        date_from: str | None = None,
        date_to: str | None = None,
        line_ids: list[int] | None = None,
        station_ids: list[str] | None = None,
        error_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Return incidents matching the supplied optional restrictions."""
        start, end = self._validate_dates(date_from, date_to)
        selected_lines = self._validate_line_ids(line_ids)
        selected_stations = _normalize_string_list(station_ids, "station_ids")
        selected_errors = _normalize_string_list(error_ids, "error_ids")

        query = (
            "SELECT incident_id, occurrence_time, error_id, error_message, "
            "line_id, station, product_number, status "
            "FROM incidents"
        )
        clauses: list[str] = []
        parameters: list[Any] = []

        if start is not None:
            clauses.append("occurrence_time >= ?")
            parameters.append(_format_mes_datetime(start))
        if end is not None:
            clauses.append("occurrence_time <= ?")
            parameters.append(_format_mes_datetime(end))
        if selected_lines:
            placeholders = ",".join("?" for _ in selected_lines)
            clauses.append(f"line_id IN ({placeholders})")
            parameters.extend(selected_lines)
        if selected_stations:
            placeholders = ",".join("?" for _ in selected_stations)
            clauses.append(f"station IN ({placeholders})")
            parameters.extend(selected_stations)
        if selected_errors:
            placeholders = ",".join("?" for _ in selected_errors)
            clauses.append(f"error_id IN ({placeholders})")
            parameters.extend(selected_errors)

        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY occurrence_time DESC, id DESC"

        rows = self._fetch_rows(query, parameters)
        incidents = [
            {
                "incident_id": str(row["incident_id"]),
                "occurrence_time": str(row["occurrence_time"]),
                "error_id": str(row["error_id"]),
                "error_message": str(row["error_message"]),
                "line_id": int(row["line_id"]),
                "station": str(row["station"]),
                "product_number": int(row["product_number"]),
                "status": _client_status(str(row["status"])),
            }
            for row in rows
        ]
        return {"incidents": incidents}

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


def _normalize_string_list(
    values: list[str] | None,
    field_name: str,
) -> list[str]:
    if values is None:
        return []

    normalized: list[str] = []
    for raw_value in values:
        value = str(raw_value).strip()
        if not value:
            raise ValueError(f"{field_name} must not contain empty values")
        if value not in normalized:
            normalized.append(value)
    return normalized


def _client_status(mes_status: str) -> str:
    if mes_status == "OPEN":
        return "OPEN"
    if mes_status == "REPAIRED":
        return "CLOSED"
    raise ValueError(f"Unsupported MES incident status: {mes_status}")


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
