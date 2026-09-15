"""Calculate deterministic production statistics from MES product events.

This module reads FINISHED product events from the existing MES production log.
It does not inspect incidents or explain why production performance changed.

Main classes:
    GetProductionStatisticsTool:
        Counts completed products for selected lines and a requested time range.

Main methods:
    execute():
        Returns per-line completed-product counts and production rates per hour.

Important notes:
    MES timestamps are timezone-naive simulated plant times. This module is
    read-only and never changes MES state or production history.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re
from typing import Any


DEFAULT_DATA_DIR = Path(__file__).resolve().parents[1] / "MES" / "data"
PRODUCTION_LOG_RELATIVE_PATH = Path("logs") / "production.log"
VALID_LINE_IDS = frozenset({1, 2, 3, 4})

_EVENT_PATTERN = re.compile(
    r"^(?P<time>[^|]+)\s*\|\s*Line (?P<line>\d+)\s*\|\s*"
    r"Product (?P<product>\d+)\s*\|\s*(?P<event>START|FINISHED)\s*$"
)


class GetProductionStatisticsTool:
    """Read MES product events and calculate deterministic line statistics."""

    def __init__(self, data_dir: Path | None = None) -> None:
        self.data_dir = Path(data_dir or DEFAULT_DATA_DIR)
        self.production_log_path = self.data_dir / PRODUCTION_LOG_RELATIVE_PATH

    def execute(
        self,
        date_from: str,
        date_to: str,
        line_ids: list[int],
    ) -> dict[str, Any]:
        """Return production counts and hourly rates for the selected lines."""
        start, end, selected_lines = self._validate_request(
            date_from,
            date_to,
            line_ids,
        )
        window_hours = (end - start).total_seconds() / 3600.0
        completed_by_line = self._count_finished_products(
            start,
            end,
            selected_lines,
        )

        lines = []
        for line_id in selected_lines:
            completed_products = completed_by_line[line_id]
            lines.append(
                {
                    "line_id": line_id,
                    "completed_products": completed_products,
                    "production_rate_per_hour": round(
                        completed_products / window_hours,
                        3,
                    ),
                }
            )

        return {
            "lines": lines,
            "total_completed_products": sum(
                item["completed_products"] for item in lines
            ),
            "total_production_rate_per_hour": round(
                sum(item["production_rate_per_hour"] for item in lines),
                3,
            ),
        }

    def _validate_request(
        self,
        date_from: str,
        date_to: str,
        line_ids: list[int],
    ) -> tuple[datetime, datetime, list[int]]:
        start = _parse_mes_datetime(date_from, "date_from")
        end = _parse_mes_datetime(date_to, "date_to")
        if end <= start:
            raise ValueError("date_to must be later than date_from")

        if not line_ids:
            raise ValueError("line_ids must contain at least one line")

        selected_lines = []
        for raw_line_id in line_ids:
            line_id = int(raw_line_id)
            if line_id not in VALID_LINE_IDS:
                raise ValueError("line_ids may contain only values 1 through 4")
            if line_id not in selected_lines:
                selected_lines.append(line_id)

        return start, end, selected_lines

    def _count_finished_products(
        self,
        start: datetime,
        end: datetime,
        line_ids: list[int],
    ) -> dict[int, int]:
        counts = {line_id: 0 for line_id in line_ids}
        if not self.production_log_path.exists():
            return counts

        with self.production_log_path.open("r", encoding="utf-8") as handle:
            for raw_line in handle:
                match = _EVENT_PATTERN.match(raw_line.strip())
                if match is None or match.group("event") != "FINISHED":
                    continue

                line_id = int(match.group("line"))
                if line_id not in counts:
                    continue

                event_time = _parse_mes_datetime(match.group("time"), "event time")
                if start <= event_time <= end:
                    counts[line_id] += 1

        return counts


def _parse_mes_datetime(value: str, field_name: str) -> datetime:
    """Parse one timezone-naive ISO timestamp used by the MES simulation."""
    try:
        parsed = datetime.fromisoformat(str(value).strip())
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a valid ISO-8601 datetime") from exc

    if parsed.tzinfo is not None:
        raise ValueError(
            f"{field_name} must be timezone-naive like the MES simulated time"
        )
    return parsed
