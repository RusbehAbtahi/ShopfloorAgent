"""Build and render one compact previous-turn context snapshot.

This module keeps conversational follow-up context grounded in structured graph
state without feeding rendered assistant prose or workflow-control fields back
to the LLM. RESPONSE captures the snapshot; LLM agents append it after normal
static AgentPrompt composition.

Main functions:
    build_previous_response_context():
        Projects RESPONSE-time state into compact conversational facts.
    append_previous_context_to_messages():
        Appends semantic supplementary context to one composed LLM message list.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .state import AgentState


_TOOL_LABELS = {
    "get_status": "current production status",
    "get_production_statistics": "production statistics",
    "list_prior_incidents": "prior incident search",
    "get_resolution_instructions": "resolution instructions",
    "get_repair_experience": "repair experience",
    "calculate_production_impact": "production impact calculation",
    "get_incident_details": "incident details",
}


def build_previous_response_context(state: AgentState) -> dict[str, Any] | None:
    """Return only previous-turn facts that can help interpret a follow-up."""
    tool = state.get("current_tool")
    arguments = dict(state.get("current_tool_arguments") or {})
    # Added on 16.09.2026: use RESPONSE presentation data so follow-up context matches what the user actually saw.
    payload = state.get("response_payload")
    payload_data = payload.get("data") if isinstance(payload, dict) else None
    result = payload_data if isinstance(payload_data, dict) else state.get("current_tool_result")

    context: dict[str, Any] = {}
    if tool is not None:
        context["tool_name"] = tool.value

    for key in ("line_ids", "station_ids"):
        values = _normalized_list(arguments.get(key))
        if values:
            context[key] = values

    error_ids = _argument_ids(arguments, "error_id", "error_ids")
    if error_ids:
        context["error_ids"] = error_ids

    incident_ids = _argument_ids(arguments, "incident_id", "incident_ids")
    if incident_ids:
        context["incident_ids"] = incident_ids

    for key in ("date_from", "date_to"):
        value = arguments.get(key)
        if value:
            context[key] = str(value)

    open_incidents = _normalized_list(state.get("open_incidents"))
    if open_incidents:
        context["open_incident_ids"] = open_incidents

    returned_incidents = _returned_incidents(result)
    if returned_incidents:
        context["returned_incidents"] = returned_incidents
        # Added on 16.09.2026: one displayed incident contributes direct facts for references such as "this type of error".
        if len(returned_incidents) == 1:
            _promote_single_incident_facts(context, returned_incidents[0])

    _carry_forward_single_incident_error(
        context,
        state.get("previous_response_context"),
    )

    return context or None


def _carry_forward_single_incident_error(
    context: dict[str, Any],
    previous_context: Any,
) -> None:
    """Keep one known incident/error association across a follow-up operation."""
    if context.get("error_ids") or not isinstance(previous_context, dict):
        return

    current_incidents = _normalized_list(context.get("incident_ids"))
    previous_incidents = _normalized_list(previous_context.get("incident_ids"))
    if len(current_incidents) != 1 or current_incidents != previous_incidents:
        return

    previous_errors = _normalized_list(previous_context.get("error_ids"))
    if len(previous_errors) == 1:
        context["error_ids"] = [previous_errors[0]]


def append_previous_context_to_messages(
    messages: list[dict[str, str]],
    context: dict[str, Any] | None,
) -> list[dict[str, str]]:
    """Append secondary previous-turn facts after normal AgentPrompt composition."""
    context_text = _render_context(context)
    if not context_text:
        return [dict(message) for message in messages]

    copied = [deepcopy(message) for message in messages]
    for message in copied:
        if str(message.get("role") or "").lower() == "system":
            current = str(message.get("content") or "").rstrip()
            message["content"] = f"{current}\n\n{context_text}" if current else context_text
            return copied

    copied.insert(0, {"role": "system", "content": context_text})
    return copied


def _render_context(context: dict[str, Any] | None) -> str:
    if not context:
        return ""

    lines = [
        "## Supplementary Previous-Turn Context",
        (
            "These facts come from the previous completed RESPONSE state. The current "
            "user request is primary. Use this context only when the current request "
            "omits needed information or clearly refers back to the previous turn. "
            "Never let previous context override an explicit value in the current "
            "request, and do not treat these facts as a new user request."
        ),
    ]

    tool_name = str(context.get("tool_name") or "")
    if tool_name:
        label = _TOOL_LABELS.get(tool_name, tool_name)
        lines.append(f"- Previous operation: {label} ({tool_name}).")

    _append_list_line(lines, context, "line_ids", "Previously resolved production lines")
    _append_list_line(lines, context, "station_ids", "Previously resolved stations")
    _append_list_line(lines, context, "error_ids", "Previously resolved error IDs")
    _append_list_line(lines, context, "incident_ids", "Previously resolved incident IDs")

    date_from = context.get("date_from")
    date_to = context.get("date_to")
    if date_from or date_to:
        lines.append(
            "- Previously used time range: "
            f"{date_from or 'unspecified'} to {date_to or 'unspecified'}."
        )

    _append_list_line(lines, context, "open_incident_ids", "Previously shown open incident IDs")

    returned = context.get("returned_incidents")
    if isinstance(returned, list) and returned:
        rendered = []
        for item in returned[:10]:
            if not isinstance(item, dict):
                continue
            incident_id = str(item.get("incident_id") or "").strip()
            if not incident_id:
                continue
            details = []
            if item.get("line_id") is not None:
                details.append(f"line {item['line_id']}")
            if item.get("error_id"):
                details.append(str(item["error_id"]))
            suffix = f" ({', '.join(details)})" if details else ""
            rendered.append(f"{incident_id}{suffix}")
        if rendered:
            lines.append("- Previously returned incidents, in displayed order: " + "; ".join(rendered) + ".")

    return "\n".join(lines)
def _argument_ids(arguments: dict[str, Any], singular: str, plural: str) -> list[Any]:
    plural_values = _normalized_list(arguments.get(plural))
    if plural_values:
        return plural_values
    singular_value = arguments.get(singular)
    return [singular_value] if singular_value not in (None, "") else []


def _normalized_list(value: Any) -> list[Any]:
    if not isinstance(value, list):
        return []
    return [item for item in value if item not in (None, "")]


def _returned_incidents(result: Any) -> list[dict[str, Any]]:
    if not isinstance(result, dict):
        return []
    candidates: list[Any] = []
    for key in ("incidents", "experiences"):
        value = result.get(key)
        if isinstance(value, list):
            candidates.extend(value)
    incident = result.get("incident")
    if isinstance(incident, dict):
        candidates.append(incident)

    compact: list[dict[str, Any]] = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        incident_id = str(item.get("incident_id") or "").strip()
        if not incident_id:
            continue
        entry: dict[str, Any] = {"incident_id": incident_id}
        if item.get("line_id") is not None:
            entry["line_id"] = item.get("line_id")
        if item.get("error_id"):
            entry["error_id"] = str(item.get("error_id"))
        if item.get("station"):
            entry["station"] = str(item.get("station"))
        compact.append(entry)
        if len(compact) >= 10:
            break
    return compact


def _promote_single_incident_facts(context: dict[str, Any], incident: dict[str, Any]) -> None:
    """Promote one displayed incident into direct facts for backward references."""
    incident_id = incident.get("incident_id")
    if incident_id and not context.get("incident_ids"):
        context["incident_ids"] = [str(incident_id)]

    line_id = incident.get("line_id")
    if line_id is not None and not context.get("line_ids"):
        context["line_ids"] = [line_id]

    error_id = incident.get("error_id")
    if error_id and not context.get("error_ids"):
        context["error_ids"] = [str(error_id)]

    station = incident.get("station")
    if station and not context.get("station_ids"):
        context["station_ids"] = [str(station)]


def _append_list_line(lines: list[str], context: dict[str, Any], key: str, label: str) -> None:
    values = context.get(key)
    if isinstance(values, list) and values:
        lines.append(f"- {label}: " + ", ".join(str(value) for value in values) + ".")
