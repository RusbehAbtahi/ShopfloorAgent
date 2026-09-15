"""Calculate deterministic production loss for one MES error type.

This module attributes downtime only to incidents matching one requested error
ID and selected production lines. Expected production uses the approved golden
cycle of one product per 90 simulated seconds per line.

Main classes:
    CalculateProductionImpactTool:
        Calculates per-line and collective projected/missed production.

Main methods:
    execute():
        Returns deterministic loss values for one error and time interval.

Important notes:
    Open incidents are capped at the latest persisted MES simulated time.
    The module performs no LLM estimation and does not attribute other causes.
"""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import sqlite3
from typing import Any


DEFAULT_DATA_DIR = Path(__file__).resolve().parents[1] / "MES" / "data"
VALID_LINE_IDS = frozenset({1, 2, 3, 4})
NOMINAL_CYCLE_SECONDS = 90.0


class CalculateProductionImpactTool:
    """Calculate deterministic production loss attributable to one error type."""

    def __init__(self, data_dir: Path | None = None) -> None:
        self.data_dir = Path(data_dir or DEFAULT_DATA_DIR)
        self.db_path = self.data_dir / "mes.sqlite"
        self.runtime_state_path = self.data_dir / "runtime_state.json"

    def execute(
        self,
        error_id: str,
        date_from: str,
        date_to: str,
        line_ids: list[int],
    ) -> dict[str, Any]:
        """Return per-line and collective impact for one selected error."""
        normalized_error_id = str(error_id).strip()
        if not normalized_error_id:
            raise ValueError("error_id is required")

        start = _parse_mes_datetime(date_from, "date_from")
        end = _parse_mes_datetime(date_to, "date_to")
        if end <= start:
            raise ValueError("date_to must be later than date_from")
        selected_lines = _validate_line_ids(line_ids)

        rows = self._load_matching_incidents(
            normalized_error_id,
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
        error_id: str,
        line_ids: list[int],
    ) -> list[sqlite3.Row]:
        if not self.db_path.exists():
            return []

        placeholders = ",".join("?" for _ in line_ids)
        query = (
            "SELECT occurrence_time, repair_time, status, line_id "
            "FROM incidents WHERE error_id = ? "
            f"AND line_id IN ({placeholders})"
        )
        parameters: list[Any] = [error_id, *line_ids]

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
