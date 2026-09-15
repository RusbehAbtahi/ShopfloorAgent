"""Return deterministic evidence for one concrete MES incident.

This module resolves one incident from SQLite, loads its stored JSON snapshot,
and returns only persisted or directly calculable incident facts. It does not
load repair guidance from other incidents or interpret evidence with an LLM.

Main classes:
    GetIncidentDetailsTool:
        Resolves one incident and its stored evidence.

Main methods:
    execute():
        Returns the complete deterministic incident record and snapshot.

Important notes:
    MES status REPAIRED is exposed as CLOSED. For OPEN incidents, current
    downtime is calculated from the latest persisted simulated plant time.
"""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import sqlite3
from typing import Any


DEFAULT_DATA_DIR = Path(__file__).resolve().parents[1] / "MES" / "data"


class GetIncidentDetailsTool:
    """Resolve one MES incident and return its persisted diagnostic evidence."""

    def __init__(self, data_dir: Path | None = None) -> None:
        self.data_dir = Path(data_dir or DEFAULT_DATA_DIR)
        self.db_path = self.data_dir / "mes.sqlite"
        self.runtime_state_path = self.data_dir / "runtime_state.json"

    def execute(self, incident_id: str) -> dict[str, Any]:
        """Return one incident with snapshot, measurements, and repair facts."""
        normalized_incident_id = str(incident_id).strip()
        if not normalized_incident_id:
            raise ValueError("incident_id is required")

        row = self._load_incident(normalized_incident_id)
        if row is None:
            return {"incident": None}

        measurements = self._parse_measurements(row["measurements_json"])
        snapshot = self._load_snapshot(str(row["snapshot_path"]))
        status = _client_status(str(row["status"]))
        downtime_seconds = self._resolve_downtime(row, status)

        incident = {
            "incident_id": str(row["incident_id"]),
            "occurrence_time": str(row["occurrence_time"]),
            "error_id": str(row["error_id"]),
            "error_message": str(row["error_message"]),
            "line_id": int(row["line_id"]),
            "station": str(row["station"]),
            "product_number": int(row["product_number"]),
            "status": status,
            "downtime_seconds": downtime_seconds,
            "snapshot_path": str(row["snapshot_path"]),
            "snapshot": snapshot,
            "measurements": measurements,
            "detector_trigger_evidence": {
                "fault_sample_time_s": row["fault_sample_time_s"],
                "measurements": measurements,
            },
            "repair_time": (
                None if row["repair_time"] is None else str(row["repair_time"])
            ),
            "repair_comment": (
                None
                if row["repair_comment"] is None
                else str(row["repair_comment"])
            ),
        }
        return {"incident": incident}

    def _load_incident(self, incident_id: str) -> sqlite3.Row | None:
        if not self.db_path.exists():
            return None

        uri = f"{self.db_path.resolve().as_uri()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=5)
        connection.row_factory = sqlite3.Row
        try:
            return connection.execute(
                """
                SELECT incident_id, error_id, error_message, station, line_id,
                       product_number, occurrence_time, repair_time,
                       downtime_seconds, status, snapshot_path, repair_comment,
                       measurements_json, fault_sample_time_s
                FROM incidents
                WHERE incident_id = ?
                """,
                (incident_id,),
            ).fetchone()
        finally:
            connection.close()

    def _load_snapshot(self, relative_path: str) -> dict[str, Any] | None:
        snapshot_path = self.data_dir / relative_path
        if not snapshot_path.exists():
            return None
        try:
            snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(
                f"Incident snapshot is invalid: {relative_path}"
            ) from exc
        if not isinstance(snapshot, dict):
            raise ValueError(f"Incident snapshot is not an object: {relative_path}")
        return snapshot

    def _parse_measurements(self, value: Any) -> dict[str, Any]:
        if value is None or value == "":
            return {}
        try:
            measurements = json.loads(str(value))
        except json.JSONDecodeError as exc:
            raise ValueError("Incident measurements_json is invalid") from exc
        if not isinstance(measurements, dict):
            raise ValueError("Incident measurements_json is not an object")
        return measurements

    def _resolve_downtime(
        self,
        row: sqlite3.Row,
        status: str,
    ) -> float | None:
        if status == "CLOSED":
            value = row["downtime_seconds"]
            return None if value is None else round(float(value), 3)

        current_time = self._load_current_simulated_time()
        if current_time is None:
            return None

        occurrence_time = _parse_mes_datetime(
            str(row["occurrence_time"]),
            "occurrence_time",
        )
        return round(
            max(0.0, (current_time - occurrence_time).total_seconds()),
            3,
        )

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


def _client_status(mes_status: str) -> str:
    if mes_status == "OPEN":
        return "OPEN"
    if mes_status == "REPAIRED":
        return "CLOSED"
    raise ValueError(f"Unsupported MES incident status: {mes_status}")


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
