"""Return the immediate deterministic Shopfloor MES status.

This module is the no-input status entry point. It checks all currently OPEN
incidents first. If any exist, it returns complete details for every open
incident. Otherwise it returns a compact one-hour production health summary.

Main classes:
    GetStatusTool:
        Resolves current fault state or healthy one-hour line status.

Main methods:
    execute():
        Returns b_ok plus either active incident details or four line summaries.

Important notes:
    Healthy statistics use the fixed previous one-hour MES simulated-time
    window. MES data is read-only; no repair or runtime mutation occurs here.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path
import sqlite3
from typing import Any

from mcp_tool_instructions import load_mcp_tool_instructions

from get_incident_details import GetIncidentDetailsTool
from get_production_statistics import GetProductionStatisticsTool


DEFAULT_DATA_DIR = Path(__file__).resolve().parents[1] / "MES" / "data"
HEALTH_WINDOW = timedelta(hours=1)
LINE_IDS = [1, 2, 3, 4]


TOOL_NAME = 'get_status'
TOOL_TITLE = 'Shopfloor Get Status'
_INSTRUCTIONS = load_mcp_tool_instructions('custom_get_status.json')
TOOL_DESCRIPTION = _INSTRUCTIONS.tool_description
SERVER_INSTRUCTIONS = _INSTRUCTIONS.server_instruction

INPUT_SCHEMA = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "b_ok": {"type": "boolean"},
        "incidents": {"type": "array", "items": {"type": "object"}},
        "last_incident_time": {},
        "lines": {"type": "array", "items": {"type": "object"}},
    },
    "required": ["b_ok"],
    "additionalProperties": False,
}


class GetStatusTool:
    """Return active incident details or the fixed one-hour healthy summary."""

    def __init__(self, data_dir: Path | None = None) -> None:
        self.data_dir = Path(data_dir or DEFAULT_DATA_DIR)
        self.db_path = self.data_dir / "mes.sqlite"
        self.runtime_state_path = self.data_dir / "runtime_state.json"
        self.incident_details = GetIncidentDetailsTool(self.data_dir)
        self.production_statistics = GetProductionStatisticsTool(self.data_dir)

    def execute(self) -> dict[str, Any]:
        """Return current system health without requiring any input arguments."""
        open_incident_ids = self._open_incident_ids()
        if open_incident_ids:
            incidents = []
            for incident_id in open_incident_ids:
                result = self.incident_details.execute(incident_id)
                incident = result.get("incident")
                if incident is not None:
                    incidents.append(incident)
            return {
                "b_ok": False,
                "incidents": incidents,
            }

        current_time = self._current_simulated_time()
        line_statistics = self._healthy_line_statistics(current_time)
        return {
            "b_ok": True,
            "last_incident_time": self._last_incident_time(),
            "lines": line_statistics,
        }

    def _open_incident_ids(self) -> list[str]:
        if not self.db_path.exists():
            return []

        uri = f"{self.db_path.resolve().as_uri()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=5)
        connection.row_factory = sqlite3.Row
        try:
            rows = connection.execute(
                """
                SELECT incident_id
                FROM incidents
                WHERE status = 'OPEN'
                ORDER BY occurrence_time DESC, id DESC
                """
            ).fetchall()
        finally:
            connection.close()
        return [str(row["incident_id"]) for row in rows]

    def _current_simulated_time(self) -> datetime | None:
        if not self.runtime_state_path.exists():
            return None
        try:
            state = json.loads(
                self.runtime_state_path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("MES runtime_state.json is invalid") from exc

        value = state.get("last_simulated_time")
        if not value:
            return None
        return _parse_mes_datetime(str(value), "last_simulated_time")

    def _healthy_line_statistics(
        self,
        current_time: datetime | None,
    ) -> list[dict[str, Any]]:
        if current_time is None:
            return [
                {
                    "line_id": line_id,
                    "status": "OK",
                    "completed_products_last_hour": 0,
                    "production_rate_per_hour": 0.0,
                }
                for line_id in LINE_IDS
            ]

        date_from = current_time - HEALTH_WINDOW
        statistics = self.production_statistics.execute(
            date_from=date_from.isoformat(timespec="milliseconds"),
            date_to=current_time.isoformat(timespec="milliseconds"),
            line_ids=LINE_IDS,
        )

        return [
            {
                "line_id": int(item["line_id"]),
                "status": "OK",
                "completed_products_last_hour": int(
                    item["completed_products"]
                ),
                "production_rate_per_hour": float(
                    item["production_rate_per_hour"]
                ),
            }
            for item in statistics["lines"]
        ]

    def _last_incident_time(self) -> str | None:
        if not self.db_path.exists():
            return None

        uri = f"{self.db_path.resolve().as_uri()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=5)
        try:
            row = connection.execute(
                """
                SELECT occurrence_time
                FROM incidents
                ORDER BY occurrence_time DESC, id DESC
                LIMIT 1
                """
            ).fetchone()
        finally:
            connection.close()

        return None if row is None else str(row[0])


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
