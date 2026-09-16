"""Reusable response configuration, help data, and Markdown formatting helpers."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from ...state import ToolName


_RESPONSE_JSON_ROOT = Path(__file__).resolve().parent.parent / "response_json"

TOOL_HELP: dict[ToolName, str] = {
    ToolName.GET_STATUS: "Current production state and active incidents.",
    ToolName.GET_PRODUCTION_STATISTICS: "Production quantities and throughput over a time interval.",
    ToolName.LIST_PRIOR_INCIDENTS: "Search or filter previously recorded incidents.",
    ToolName.GET_RESOLUTION_INSTRUCTIONS: "Official resolution instructions for known error IDs.",
    ToolName.GET_REPAIR_EXPERIENCE: "Historical repair experience for a specific error.",
    ToolName.CALCULATE_PRODUCTION_IMPACT: "Production loss or impact caused by selected incidents.",
    ToolName.GET_INCIDENT_DETAILS: "Detailed information for one specific incident.",
}

ARGUMENT_HELP: dict[ToolName, dict[str, Any]] = {
    ToolName.GET_STATUS: {
        "arguments": "No arguments required.",
        "example": "get_status()",
    },
    ToolName.GET_PRODUCTION_STATISTICS: {
        "arguments": "Required temporal scope: a date range, a full calendar day, or an explicit whole-period request. Optional line_ids. Omitted lines use all production lines.",
        "example": 'get_production_statistics(date_from="2026-09-15T08:00:00", date_to="2026-09-15T09:00:00", line_ids=[1])',
    },
    ToolName.LIST_PRIOR_INCIDENTS: {
        "arguments": "Optional date_from, date_to, line_ids, station_ids, and error_ids. When dates are omitted, the full available incident history is used.",
        "example": "list_prior_incidents()",
    },
    ToolName.GET_RESOLUTION_INSTRUCTIONS: {
        "arguments": "Optional: `error_ids` as a list of error IDs.",
        "example": 'get_resolution_instructions(error_ids=["S1_ALIGNMENT_FAILED"])',
    },
    ToolName.GET_REPAIR_EXPERIENCE: {
        "arguments": "Required error_id. Optional date_from, date_to, and line_ids. When dates are omitted, the full available repair history is used.",
        "example": 'get_repair_experience(error_id="S1_ALIGNMENT_FAILED")',
    },
    ToolName.CALCULATE_PRODUCTION_IMPACT: {
        "arguments": "Required temporal scope: a date range, full calendar day, incident day, or explicit whole period. incident_ids may fall back to current open incidents. line_ids may be derived from the selected incidents.",
        "example": 'calculate_production_impact(incident_ids=["INC-000003"], date_from="2026-09-15T00:00:00", date_to="2026-09-16T00:00:00")',
    },
    ToolName.GET_INCIDENT_DETAILS: {
        "arguments": "Optional: one `incident_id`; when omitted, current status is used.",
        "example": 'get_incident_details(incident_id="INC-000003")',
    },
}


@lru_cache(maxsize=None)
def load_response_json(name: str) -> dict[str, Any]:
    """Load one response JSON file once and reuse it for the process lifetime."""
    path = _RESPONSE_JSON_ROOT / f"{name}.json"
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"Response JSON must contain an object: {path}")
    return data


def tool_help_markdown() -> str:
    """Return reusable Markdown help for every supported ProductionAgent tool."""
    return "\n".join(
        f"- **`{tool.value}`** — {description}"
        for tool, description in TOOL_HELP.items()
    )


def argument_help_markdown(tool: ToolName | None) -> str:
    """Return reusable Markdown argument guidance for the selected tool."""
    if tool is None or tool not in ARGUMENT_HELP:
        return "No valid tool is currently selected."

    help_data = ARGUMENT_HELP[tool]
    return (
        f"**Arguments:** {help_data['arguments']}\n\n"
        "**Example**\n\n"
        f"```text\n{help_data['example']}\n```"
    )


def issues_markdown(data: Any) -> str:
    """Format semantic validation issues carried by response_payload data."""
    if not isinstance(data, dict):
        return "- The supplied arguments could not be validated."

    issues = data.get("issues")
    if isinstance(issues, list):
        clean = [str(issue).strip() for issue in issues if str(issue).strip()]
        if clean:
            return "\n".join(f"- {issue}" for issue in clean)

    return "- The supplied arguments could not be validated."



_DATE_AWARE_TOOLS = frozenset((
    ToolName.GET_PRODUCTION_STATISTICS,
    ToolName.LIST_PRIOR_INCIDENTS,
    ToolName.GET_REPAIR_EXPERIENCE,
    ToolName.CALCULATE_PRODUCTION_IMPACT,
))


def tool_result_markdown(
    data: Any,
    tool: Optional[ToolName] = None,
    arguments: Optional[dict[str, Any]] = None,
) -> str:
    """Render tool output with transparent time scope and user-friendly units."""
    lines: list[str] = []

    # Added on 16.09.2026: always expose the effective range used by date-aware tools.
    if tool in _DATE_AWARE_TOOLS and arguments:
        date_from = arguments.get("date_from")
        date_to = arguments.get("date_to")
        if date_from or date_to:
            lines.extend([
                "#### Effective Time Range",
                "",
                f"- **From:** {date_from or 'unspecified'}",
                f"- **To:** {date_to or 'unspecified'}",
                "",
            ])

    if not isinstance(data, dict):
        lines.append(f"- **Result:** {_scalar(data)}")
        return "\n".join(lines).strip()

    _append_mapping(lines, data, level=0)
    return "\n".join(lines).strip()



def _append_mapping(lines: list[str], mapping: dict[str, Any], level: int) -> None:
    for key, value in mapping.items():
        label = _label(key)

        if isinstance(value, dict):
            lines.extend([f"{'#' * min(4, level + 4)} {label}", ""])
            _append_mapping(lines, value, level + 1)
            lines.append("")
            continue

        if isinstance(value, list):
            lines.extend([f"{'#' * min(4, level + 4)} {label}", ""])
            _append_list(lines, value, level + 1)
            lines.append("")
            continue

        lines.append(f"- **{label}:** {_format_field(key, value)}")


def _append_list(lines: list[str], values: list[Any], level: int) -> None:
    if not values:
        lines.append("- None")
        return

    for index, item in enumerate(values, start=1):
        if isinstance(item, dict):
            if item.get("line_id") is not None:
                lines.append(f"**Line {item['line_id']}**")
            elif item.get("incident_id"):
                lines.append(f"**Incident {item['incident_id']}**")
            else:
                lines.append(f"**{index}.**")

            for key, value in item.items():
                label = _label(key)
                if isinstance(value, (dict, list)):
                    rendered = json.dumps(value, ensure_ascii=False, default=str)
                    lines.append(f"- **{label}:** {rendered}")
                else:
                    lines.append(f"- **{label}:** {_format_field(key, value)}")
            lines.append("")
        else:
            lines.append(f"- {_scalar(item)}")



def _format_field(key: Any, value: Any) -> str:
    normalized_key = str(key).strip().lower()

    if normalized_key == "downtime_seconds" and isinstance(value, (int, float)):
        return _format_duration(value)

    if normalized_key.endswith("_percent") and isinstance(value, (int, float)):
        return f"{_trim_number(value)}%"

    if normalized_key.endswith("_products") and isinstance(value, (int, float)):
        return str(int(round(float(value))))

    return _scalar(value)


def _format_duration(value: Any) -> str:
    total_seconds = max(0, int(round(float(value))))
    days, remainder = divmod(total_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)

    parts: list[str] = []
    if days:
        parts.append(_duration_part(days, "day"))
    if hours:
        parts.append(_duration_part(hours, "hour"))
    if minutes:
        parts.append(_duration_part(minutes, "minute"))
    if seconds or not parts:
        parts.append(_duration_part(seconds, "second"))
    return " ".join(parts)


def _duration_part(value: int, unit: str) -> str:
    suffix = "" if value == 1 else "s"
    return f"{value} {unit}{suffix}"


def _trim_number(value: Any) -> str:
    number = float(value)
    if number.is_integer():
        return str(int(number))
    return f"{number:.2f}".rstrip("0").rstrip(".")


def _label(value: Any) -> str:
    return str(value).replace("_", " ").strip().title()


def _scalar(value: Any) -> str:
    if value is None:
        return "None"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, (int, float)):
        return _trim_number(value)
    return str(value)

