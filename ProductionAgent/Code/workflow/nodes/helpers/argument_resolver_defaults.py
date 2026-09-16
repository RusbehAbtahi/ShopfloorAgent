"""Provide deterministic MES-backed defaults for ProductionAgent arguments.

This module owns only default construction that requires persisted MES facts.
It does not parse user language, manage clarification state, or validate final
LLM output beyond the minimum needed to read the requested MES records.

Main functions:
    apply_tool_defaults():
        Fill optional concrete arguments required by selected MCP tools.
    current_mes_datetime():
        Return the persisted simulated time used for relative-date synthesis.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path
import sqlite3
from typing import Any, Optional

from ...state import ToolName


MES_DATA_DIR = Path(__file__).resolve().parents[5] / "MES" / "data"


def apply_tool_defaults(
    tool: ToolName,
    arguments: dict[str, Any],
    user_request: Optional[str] = None,
) -> tuple[dict[str, Any], list[str]]:
    """Fill deterministic MES-backed defaults and enforce approved date policy."""
    result = dict(arguments)
    errors: list[str] = []
    request_text = str(user_request or "").strip().lower()
    full_history = _requests_full_history(request_text)
    incident_day = _requests_incident_day(request_text)

    # Added on 16.09.2026: dates are tool-specific instead of silently defaulting every tool.
    if tool == ToolName.GET_PRODUCTION_STATISTICS:
        if result.get("line_ids") is None:
            result["line_ids"] = [1, 2, 3, 4]
        result, date_errors = _statistics_date_defaults(result, full_history)
        errors.extend(date_errors)

    elif tool == ToolName.LIST_PRIOR_INCIDENTS:
        result, date_errors = _history_date_defaults(
            result,
            _incident_history_bounds(),
        )
        errors.extend(date_errors)

    elif tool == ToolName.GET_REPAIR_EXPERIENCE:
        result, date_errors = _history_date_defaults(
            result,
            _repair_history_bounds(),
        )
        errors.extend(date_errors)

    elif tool == ToolName.CALCULATE_PRODUCTION_IMPACT:
        result, impact_errors = _impact_defaults(
            result,
            full_history=full_history,
            incident_day=incident_day,
        )
        errors.extend(impact_errors)

    return result, errors


def current_mes_datetime() -> str | None:
    """Return the persisted MES simulated time for relative-date synthesis."""
    value = _load_current_simulated_time()
    return value.isoformat(timespec="seconds") if value is not None else None

def _statistics_date_defaults(
    arguments: dict[str, Any],
    full_history: bool,
) -> tuple[dict[str, Any], list[str]]:
    result = dict(arguments)
    if result.get("date_from") is not None and result.get("date_to") is not None:
        return result, []

    if full_history and result.get("date_from") is None and result.get("date_to") is None:
        first_event, last_event = _production_log_bounds()
        current_time = _load_current_simulated_time() or last_event
        if first_event is None or current_time is None:
            return result, ["Unable to determine the full production-history time range from MES data."]
        result["date_from"] = first_event.isoformat(timespec="seconds")
        result["date_to"] = current_time.isoformat(timespec="seconds")
        return result, []

    return result, [
        "get_production_statistics requires a date/time scope: a date range, a full calendar day, or an explicit whole-period request."
    ]


def _history_date_defaults(
    arguments: dict[str, Any],
    bounds: tuple[Optional[datetime], Optional[datetime]],
) -> tuple[dict[str, Any], list[str]]:
    result = dict(arguments)
    start, end = bounds
    errors: list[str] = []

    if result.get("date_from") is None:
        if start is None:
            errors.append("Unable to determine the beginning of the available MES history.")
        else:
            result["date_from"] = start.isoformat(timespec="seconds")

    if result.get("date_to") is None:
        if end is None:
            errors.append("Unable to determine the end of the available MES history.")
        else:
            result["date_to"] = end.isoformat(timespec="seconds")

    return result, errors


def _requests_full_history(request_text: str) -> bool:
    phrases = (
        "whole period",
        "all available history",
        "all available",
        "from the beginning",
        "entire history",
        "full history",
        "whole history",
        "all history",
        "whole date",
    )
    return any(phrase in request_text for phrase in phrases)


def _requests_incident_day(request_text: str) -> bool:
    phrases = (
        "impact day",
        "incident day",
        "day of the incident",
        "day this incident occurred",
        "day that incident occurred",
    )
    return any(phrase in request_text for phrase in phrases)



def _impact_defaults(
    arguments: dict[str, Any],
    *,
    full_history: bool,
    incident_day: bool,
) -> tuple[dict[str, Any], list[str]]:
    result = dict(arguments)
    errors: list[str] = []

    incident_ids = result.get("incident_ids")
    automatic_open_fallback = incident_ids is None
    open_rows: list[sqlite3.Row] = []
    if automatic_open_fallback:
        open_rows = _load_open_incident_rows()
        if open_rows:
            incident_ids = [str(row["incident_id"]) for row in open_rows]
            result["incident_ids"] = incident_ids

    if not isinstance(incident_ids, list) or not incident_ids:
        if result.get("date_from") is None and result.get("date_to") is None and not full_history and not incident_day:
            errors.append("calculate_production_impact requires a date/time scope: a date range, a full calendar day, incident day, or an explicit whole-period request.")
        return result, errors

    normalized_ids, list_error = _normalize_incident_ids(incident_ids)
    if list_error:
        return result, [list_error]

    rows = open_rows if automatic_open_fallback else _load_incident_rows(normalized_ids)
    found_ids = {str(row["incident_id"]) for row in rows}
    missing_ids = [value for value in normalized_ids if value not in found_ids]
    if missing_ids:
        errors.append("Unknown incident_id(s): " + ", ".join(missing_ids) + ".")
        return result, errors

    if result.get("line_ids") is None:
        result["line_ids"] = list(dict.fromkeys(int(row["line_id"]) for row in rows))


    date_from = result.get("date_from")
    date_to = result.get("date_to")

    if date_from is not None and date_to is not None:
        return result, errors

    if date_from is not None or date_to is not None:
        errors.append("calculate_production_impact requires both date_from and date_to for a bounded calculation.")
        return result, errors

    starts = [datetime.fromisoformat(str(row["occurrence_time"])) for row in rows]

    if incident_day:
        incident_days = []
        for value in starts:
            value_day = value.date()
            if value_day not in incident_days:
                incident_days.append(value_day)

        if len(incident_days) not in (1,):
            errors.append("Selected incidents occurred on different calendar days. Specify the impact date or an explicit date range.")
            return result, errors

        day = incident_days[0]
        start = datetime.combine(day, datetime.min.time())
        result["date_from"] = start.isoformat(timespec="seconds")
        result["date_to"] = (start + timedelta(days=1)).isoformat(timespec="seconds")
        return result, errors


    if full_history:
        current_time = _load_current_simulated_time()
        ends: list[datetime] = []
        for row in rows:
            if str(row["status"]) == "OPEN":
                if current_time is None:
                    errors.append("Unable to determine current MES time for an open incident.")
                    return result, errors
                ends.append(current_time)
                continue
            repair_time = row["repair_time"]
            if repair_time is not None:
                ends.append(datetime.fromisoformat(str(repair_time)))

        if not ends:
            errors.append("Unable to determine the full impact period for the selected incidents.")
            return result, errors

        result["date_from"] = min(starts).isoformat(timespec="seconds")
        result["date_to"] = max(ends).isoformat(timespec="seconds")
        return result, errors

    errors.append("calculate_production_impact requires a date/time scope: a date range, a full calendar day, incident day, or an explicit whole-period request.")
    return result, errors


def _normalize_incident_ids(value: list[Any]) -> tuple[list[str], str | None]:
    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            return [], "incident_ids must contain only non-empty strings."
        clean_item = item.strip()
        if clean_item not in normalized:
            normalized.append(clean_item)
    return normalized, None


def _load_current_simulated_time() -> datetime | None:
    path = MES_DATA_DIR / "runtime_state.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        raw_value = data.get("last_simulated_time")
        if not raw_value:
            return None
        parsed = datetime.fromisoformat(str(raw_value).strip())
    except (OSError, json.JSONDecodeError, ValueError):
        return None
    return parsed if parsed.tzinfo is None else None


def _production_log_bounds() -> tuple[datetime | None, datetime | None]:
    path = MES_DATA_DIR / "logs" / "production.log"
    if not path.exists():
        return None, None

    timestamps: list[datetime] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for raw_line in handle:
                if "|" not in raw_line:
                    continue
                raw_time = raw_line.split("|", 1)[0].strip()
                try:
                    parsed = datetime.fromisoformat(raw_time)
                except ValueError:
                    continue
                if parsed.tzinfo is None:
                    timestamps.append(parsed)
    except OSError:
        return None, None

    if not timestamps:
        return None, None
    return min(timestamps), max(timestamps)


def _incident_history_bounds() -> tuple[Optional[datetime], Optional[datetime]]:
    return _database_history_bounds(repaired_only=False)


def _repair_history_bounds() -> tuple[Optional[datetime], Optional[datetime]]:
    return _database_history_bounds(repaired_only=True)


def _database_history_bounds(
    *,
    repaired_only: bool,
) -> tuple[Optional[datetime], Optional[datetime]]:
    db_path = MES_DATA_DIR / "mes.sqlite"
    if not db_path.exists():
        return None, None

    query = "SELECT MIN(occurrence_time), MAX(COALESCE(repair_time, occurrence_time)) FROM incidents"
    if repaired_only:
        query += " WHERE status = 'REPAIRED'"

    uri = f"{db_path.resolve().as_uri()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=5)
    try:
        row = connection.execute(query).fetchone()
    finally:
        connection.close()

    if row is None or row[0] is None:
        return None, None

    start = datetime.fromisoformat(str(row[0]))
    last = datetime.fromisoformat(str(row[1])) if row[1] is not None else start
    end = _load_current_simulated_time() or last
    return start, end


def _load_open_incident_rows() -> list[sqlite3.Row]:
    db_path = MES_DATA_DIR / "mes.sqlite"
    if not db_path.exists():
        return []

    uri = f"{db_path.resolve().as_uri()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=5)
    connection.row_factory = sqlite3.Row
    try:
        return connection.execute(
            "SELECT incident_id, occurrence_time, repair_time, status, line_id "
            "FROM incidents WHERE status = 'OPEN' ORDER BY occurrence_time ASC, id ASC"
        ).fetchall()
    finally:
        connection.close()


def _load_incident_rows(incident_ids: list[str]) -> list[sqlite3.Row]:
    db_path = MES_DATA_DIR / "mes.sqlite"
    if not db_path.exists() or not incident_ids:
        return []

    placeholders = ",".join("?" for _ in incident_ids)
    uri = f"{db_path.resolve().as_uri()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=5)
    connection.row_factory = sqlite3.Row
    try:
        return connection.execute(
            "SELECT incident_id, occurrence_time, repair_time, status, line_id "
            f"FROM incidents WHERE incident_id IN ({placeholders})",
            incident_ids,
        ).fetchall()
    finally:
        connection.close()
