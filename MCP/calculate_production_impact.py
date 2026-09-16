"""Calculate deterministic production loss for selected MES incidents.

This module attributes downtime only to the requested incident IDs and selected
production lines. Expected production uses the approved golden cycle of one
product per 90 simulated seconds per line.

Main classes:
    CalculateProductionImpactTool:
        Calculates per-line and collective projected/missed production.

Main methods:
    execute():
        Returns deterministic loss values for selected incidents in one interval.

Important notes:
    Open incidents are capped at the latest persisted MES simulated time.
    The module performs no LLM estimation and does not select incidents itself.
"""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import sqlite3
from typing import Any

from mcp_tool_instructions import load_mcp_tool_instructions


DEFAULT_DATA_DIR = Path(__file__).resolve().parents[1] / "MES" / "data"
VALID_LINE_IDS = frozenset({1, 2, 3, 4})
NOMINAL_CYCLE_SECONDS = 90.0


TOOL_NAME = 'calculate_production_impact'
TOOL_TITLE = 'Shopfloor Production Impact'
_INSTRUCTIONS = load_mcp_tool_instructions('custom_calculate_production_impact.json')
TOOL_DESCRIPTION = _INSTRUCTIONS.tool_description
SERVER_INSTRUCTIONS = _INSTRUCTIONS.server_instruction

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "incident_ids": {"type": "array", "items": {"type": "string", "minLength": 1}, "minItems": 1, "uniqueItems": True, "description": _INSTRUCTIONS.field_descriptions["incident_ids"]},
        "date_from": {"type": "string", "minLength": 1, "description": _INSTRUCTIONS.field_descriptions["date_from"]},
        "date_to": {"type": "string", "minLength": 1, "description": _INSTRUCTIONS.field_descriptions["date_to"]},
        "line_ids": {"type": "array", "items": {"type": "integer", "enum": [1, 2, 3, 4]}, "minItems": 1, "maxItems": 4, "uniqueItems": True, "description": _INSTRUCTIONS.field_descriptions["line_ids"]},
    },
    "required": ["incident_ids", "date_from", "date_to", "line_ids"],
    "additionalProperties": False,
}

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "lines": {"type": "array", "items": {"type": "object"}},
        "total_projected_products": {"type": "number"},
        "total_missed_products": {"type": "number"},
        "total_loss_percent": {"type": "number"},
    },
    "required": ["lines", "total_projected_products", "total_missed_products", "total_loss_percent"],
    "additionalProperties": False,
}


class CalculateProductionImpactTool:
    """Calculate deterministic production loss for selected incident IDs."""

    def __init__(self, data_dir: Path | None = None) -> None:
        self.data_dir = Path(data_dir or DEFAULT_DATA_DIR)
        self.db_path = self.data_dir / "mes.sqlite"
        self.runtime_state_path = self.data_dir / "runtime_state.json"

    def execute(
        self,
        incident_ids: list[str],
        date_from: str,
        date_to: str,
        line_ids: list[int],
    ) -> dict[str, Any]:
        """Return per-line and collective impact for selected incidents."""
        selected_incident_ids = _normalize_incident_ids(incident_ids)
        start = _parse_mes_datetime(date_from, "date_from")
        end = _parse_mes_datetime(date_to, "date_to")
        if end <= start:
            raise ValueError("date_to must be later than date_from")
        selected_lines = _validate_line_ids(line_ids)

        rows = self._load_matching_incidents(
            selected_incident_ids,
            selected_lines,
        )
        current_simulated_time = self._load_current_simulated_time()
        window_seconds = (end - start).total_seconds()

        lines = []
        for line_id in selected_lines:
            downtime_seconds = self._line_downtime(
                rows,
                line_id,
                start,
                end,
                current_simulated_time,
            )
            projected_products = window_seconds / NOMINAL_CYCLE_SECONDS
            missed_products = downtime_seconds / NOMINAL_CYCLE_SECONDS
            loss_percent = (
                missed_products / projected_products * 100.0
                if projected_products > 0
                else 0.0
            )
            lines.append(
                {
                    "line_id": line_id,
                    "downtime_seconds": round(downtime_seconds, 3),
                    "projected_products": round(projected_products, 3),
                    "missed_products": round(missed_products, 3),
                    "loss_percent": round(loss_percent, 2),
                }
            )

        total_projected = sum(item["projected_products"] for item in lines)
        total_missed = sum(item["missed_products"] for item in lines)
        total_loss_percent = (
            total_missed / total_projected * 100.0
            if total_projected > 0
            else 0.0
        )
        return {
            "lines": lines,
            "total_projected_products": round(total_projected, 3),
            "total_missed_products": round(total_missed, 3),
            "total_loss_percent": round(total_loss_percent, 2),
        }

    def _load_matching_incidents(
        self,
        incident_ids: list[str],
        line_ids: list[int],
    ) -> list[sqlite3.Row]:
        if not self.db_path.exists():
            return []

        incident_placeholders = ",".join("?" for _ in incident_ids)
        line_placeholders = ",".join("?" for _ in line_ids)
        query = (
            "SELECT occurrence_time, repair_time, status, line_id "
            f"FROM incidents WHERE incident_id IN ({incident_placeholders}) "
            f"AND line_id IN ({line_placeholders})"
        )
        parameters: list[Any] = [*incident_ids, *line_ids]

        uri = f"{self.db_path.resolve().as_uri()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=5)
        connection.row_factory = sqlite3.Row
        try:
            return connection.execute(query, parameters).fetchall()
        finally:
            connection.close()

    def _load_current_simulated_time(self) -> datetime | None:
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

    def _line_downtime(
        self,
        rows: list[sqlite3.Row],
        line_id: int,
        start: datetime,
        end: datetime,
        current_simulated_time: datetime | None,
    ) -> float:
        downtime = 0.0
        for row in rows:
            if int(row["line_id"]) != line_id:
                continue

            incident_start = _parse_mes_datetime(
                str(row["occurrence_time"]),
                "occurrence_time",
            )
            if str(row["status"]) == "OPEN":
                incident_end = current_simulated_time or end
            else:
                repair_time = row["repair_time"]
                if repair_time is None:
                    continue
                incident_end = _parse_mes_datetime(
                    str(repair_time),
                    "repair_time",
                )

            overlap_start = max(start, incident_start)
            overlap_end = min(end, incident_end)
            if overlap_end > overlap_start:
                downtime += (overlap_end - overlap_start).total_seconds()

        return min(downtime, (end - start).total_seconds())


def _normalize_incident_ids(incident_ids: list[str]) -> list[str]:
    if not isinstance(incident_ids, list) or not incident_ids:
        raise ValueError("incident_ids must contain at least one incident ID")

    normalized: list[str] = []
    for raw_incident_id in incident_ids:
        if not isinstance(raw_incident_id, str) or not raw_incident_id.strip():
            raise ValueError("incident_ids must contain only non-empty strings")
        incident_id = raw_incident_id.strip()
        if incident_id not in normalized:
            normalized.append(incident_id)
    return normalized


def _validate_line_ids(line_ids: list[int]) -> list[int]:
    if not line_ids:
        raise ValueError("line_ids must contain at least one line")

    selected_lines: list[int] = []
    for raw_line_id in line_ids:
        line_id = int(raw_line_id)
        if line_id not in VALID_LINE_IDS:
            raise ValueError("line_ids may contain only values 1 through 4")
        if line_id not in selected_lines:
            selected_lines.append(line_id)
    return selected_lines


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
