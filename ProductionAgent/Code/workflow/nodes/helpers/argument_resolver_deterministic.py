"""Deterministically merge, default, and validate ProductionAgent arguments.

The resolver owns strict Python-like call parsing and all post-LLM contract
handling. LLM candidates are never executable until this module has merged
retained values, applied deterministic defaults, and validated the selected
tool contract.

Main classes:
    DeterministicArgumentResolver:
        Resolves strict calls and validates extracted argument candidates.

Main methods:
    run():
        Resolves a direct canonical tool call or returns None for LLM fallback.
    resolve_extracted():
        Merges LLM candidates and returns ready or clarification state.

Important notes:
    MES-backed defaults are read-only and use the persisted simulated time.
"""

from __future__ import annotations

import ast
from datetime import datetime
import re
from typing import Any

from ...state import AgentState, PendingInteraction, Phase, ToolName
from .argument_resolver_defaults import apply_tool_defaults


MAX_ARGUMENT_ATTEMPTS = 5
VALID_LINE_IDS = {1, 2, 3, 4}
_REQUIRED_ARGUMENTS: dict[ToolName, tuple[str, ...]] = {
    ToolName.GET_STATUS: (),
    ToolName.GET_PRODUCTION_STATISTICS: (),
    ToolName.LIST_PRIOR_INCIDENTS: (),
    ToolName.GET_RESOLUTION_INSTRUCTIONS: (),
    ToolName.GET_REPAIR_EXPERIENCE: ("error_id",),
    ToolName.CALCULATE_PRODUCTION_IMPACT: ("incident_ids",),
    ToolName.GET_INCIDENT_DETAILS: (),
}

_ALLOWED_ARGUMENTS: dict[ToolName, tuple[str, ...]] = {
    ToolName.GET_STATUS: (),
    ToolName.GET_PRODUCTION_STATISTICS: ("date_from", "date_to", "line_ids"),
    ToolName.LIST_PRIOR_INCIDENTS: (
        "date_from",
        "date_to",
        "line_ids",
        "station_ids",
        "error_ids",
    ),
    ToolName.GET_RESOLUTION_INSTRUCTIONS: ("error_ids",),
    ToolName.GET_REPAIR_EXPERIENCE: (
        "error_id",
        "date_from",
        "date_to",
        "line_ids",
    ),
    ToolName.CALCULATE_PRODUCTION_IMPACT: (
        "incident_ids",
        "date_from",
        "date_to",
        "line_ids",
    ),
    ToolName.GET_INCIDENT_DETAILS: ("incident_id",),
}


class DeterministicArgumentResolver:
    """Own deterministic parsing, defaults, validation, and retry state."""

    def run(self, state: AgentState) -> dict[str, Any] | None:
        """Resolve a direct canonical call or return None for natural-language LLM fallback."""
        current_tool = state.get("current_tool")
        if current_tool is None:
            return self._clarification_response(state, "No tool is currently selected.")

        if current_tool == ToolName.GET_STATUS:
            return self._ready_update(current_tool, {})

        request = str(state.get("current_request") or "").strip()
        if not any(request.startswith(f"{tool.value}(") for tool in ToolName):
            return None

        parsed_name, parsed_arguments, parse_error = self._parse_call(request)
        previous_arguments = dict(state.get("current_tool_arguments") or {})
        allowed_names = set(_ALLOWED_ARGUMENTS[current_tool])
        parsed_known_arguments = {
            key: value
            for key, value in parsed_arguments.items()
            if key in allowed_names and value is not None
        }
        merged_arguments = {**previous_arguments, **parsed_known_arguments}

        errors: list[str] = []
        if parse_error:
            errors.append(parse_error)
        if parsed_name and parsed_name != current_tool.value:
            errors.append(
                f"The selected tool is {current_tool.value}, not {parsed_name}."
            )

        unexpected_arguments = sorted(set(parsed_arguments) - allowed_names)
        if unexpected_arguments:
            errors.append(
                "Unexpected argument(s): " + ", ".join(unexpected_arguments) + "."
            )

        return self._finalize(state, current_tool, merged_arguments, errors)

    def resolve_extracted(
        self,
        state: AgentState,
        extracted_arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Merge LLM candidates with retained arguments and validate deterministically."""
        current_tool = state.get("current_tool")
        if current_tool is None:
            return self._clarification_response(state, "No tool is currently selected.")

        prepared, preparation_errors = self._prepare_extracted_arguments(
            current_tool,
            extracted_arguments,
        )
        # Added on 16.09.2026: make single-error backward references reliable even when the argument LLM returns null.
        self._apply_previous_error_reference(state, current_tool, prepared)
        previous_arguments = dict(state.get("current_tool_arguments") or {})
        new_values = {
            key: value
            for key, value in prepared.items()
            if value is not None
        }
        merged_arguments = {**previous_arguments, **new_values}
        return self._finalize(
            state,
            current_tool,
            merged_arguments,
            preparation_errors,
        )

    @staticmethod
    def _apply_previous_error_reference(
        state: AgentState,
        tool: ToolName,
        prepared: dict[str, Any],
    ) -> None:
        """Reuse one explicit previous error fact for a clear backward reference."""
        if tool != ToolName.GET_REPAIR_EXPERIENCE or prepared.get("error_id"):
            return

        request = str(state.get("current_request") or "").strip()
        if re.search(r"\b(this|that|it|same|previous|above)\b", request, re.IGNORECASE) is None:
            return
        # An explicit error-code-shaped value in the current request must never be
        # replaced by previous-turn context, even if the LLM failed to extract it.
        if re.search(r"\bS[123]_[A-Z0-9_]+\b", request, re.IGNORECASE) is not None:
            return

        context = state.get("previous_response_context")
        if not isinstance(context, dict):
            return
        previous_errors = context.get("error_ids")
        if not isinstance(previous_errors, list) or len(previous_errors) != 1:
            return

        error_id = previous_errors[0]
        if isinstance(error_id, str) and error_id.strip():
            prepared["error_id"] = error_id.strip()

    def _prepare_extracted_arguments(
        self,
        tool: ToolName,
        extracted: dict[str, Any],
    ) -> tuple[dict[str, Any], list[str]]:
        prepared: dict[str, Any] = {}
        errors: list[str] = []
        allowed_names = set(_ALLOWED_ARGUMENTS[tool])

        for name in ("date_from", "date_to", "line_ids", "station_ids"):
            value = extracted.get(name)
            if name in allowed_names and value is not None:
                prepared[name] = value

        error_ids = extracted.get("error_ids")
        if error_ids is not None:
            normalized_errors, list_error = _normalize_string_list(
                error_ids,
                "error_ids",
            )
            if list_error:
                errors.append(list_error)
            elif tool == ToolName.GET_REPAIR_EXPERIENCE:
                if len(normalized_errors) == 1:
                    prepared["error_id"] = normalized_errors[0]
                elif len(normalized_errors) > 1:
                    errors.append(
                        "get_repair_experience requires exactly one error_id."
                    )
            elif "error_ids" in allowed_names:
                prepared["error_ids"] = normalized_errors

        incident_ids = extracted.get("incident_ids")
        if incident_ids is not None:
            normalized_incidents, list_error = _normalize_string_list(
                incident_ids,
                "incident_ids",
            )
            if list_error:
                errors.append(list_error)
            elif tool == ToolName.GET_INCIDENT_DETAILS:
                if len(normalized_incidents) == 1:
                    prepared["incident_id"] = normalized_incidents[0]
                elif len(normalized_incidents) > 1:
                    errors.append(
                        "get_incident_details accepts exactly one incident_id."
                    )
            elif "incident_ids" in allowed_names:
                prepared["incident_ids"] = normalized_incidents

        return prepared, errors

    def _finalize(
        self,
        state: AgentState,
        tool: ToolName,
        arguments: dict[str, Any],
        initial_errors: list[str],
    ) -> dict[str, Any]:
        errors = list(initial_errors)

        if (
            tool == ToolName.GET_INCIDENT_DETAILS
            and not errors
            and not str(arguments.get("incident_id") or "").strip()
        ):
            return self._ready_update(ToolName.GET_STATUS, {})

        # Added on 16.09.2026: deterministic date policy also uses explicit temporal wording from the current request.
        defaulted_arguments, default_errors = apply_tool_defaults(
            tool,
            arguments,
            user_request=str(state.get("current_request") or ""),
        )
        errors.extend(default_errors)

        normalized_arguments, validation_errors = self._validate_arguments(
            tool,
            defaulted_arguments,
        )
        if (
            tool == ToolName.GET_REPAIR_EXPERIENCE
            and any("requires exactly one error_id" in issue for issue in errors)
        ):
            validation_errors = [
                issue
                for issue in validation_errors
                if issue != "Missing required argument: error_id."
            ]
        errors.extend(validation_errors)

        if errors:
            return self._clarification_response(
                state,
                " ".join(errors),
                partial_arguments=normalized_arguments,
            )

        updates = self._ready_update(tool, normalized_arguments)
        updates.update(self._focus_updates(normalized_arguments))
        return updates

    def _parse_call(
        self,
        request: str,
    ) -> tuple[str | None, dict[str, Any], str | None]:
        """Safely parse one Python-like function call without executing code."""
        try:
            expression = ast.parse(request.strip(), mode="eval").body
        except SyntaxError:
            return None, {}, "The request is not a valid tool-call expression."

        if not isinstance(expression, ast.Call) or not isinstance(
            expression.func,
            ast.Name,
        ):
            return None, {}, "Use one direct function call with parentheses."

        if expression.args:
            return expression.func.id, {}, "Use named arguments only."

        arguments: dict[str, Any] = {}
        for keyword in expression.keywords:
            if keyword.arg is None:
                return expression.func.id, arguments, "Do not use **kwargs syntax."
            if keyword.arg in arguments:
                return (
                    expression.func.id,
                    arguments,
                    f"Argument {keyword.arg} was provided more than once.",
                )
            try:
                arguments[keyword.arg] = ast.literal_eval(keyword.value)
            except (ValueError, TypeError):
                return (
                    expression.func.id,
                    arguments,
                    f"Argument {keyword.arg} must be a literal value.",
                )

        return expression.func.id, arguments, None

    def _validate_arguments(
        self,
        tool: ToolName,
        arguments: dict[str, Any],
    ) -> tuple[dict[str, Any], list[str]]:
        normalized = dict(arguments)
        errors: list[str] = []

        for name in _REQUIRED_ARGUMENTS[tool]:
            value = normalized.get(name)
            if value is None or value == "" or value == []:
                errors.append(f"Missing required argument: {name}.")

        for name in ("error_id", "incident_id"):
            if name in normalized and normalized[name] is not None:
                value = normalized[name]
                if not isinstance(value, str) or not value.strip():
                    errors.append(f"{name} must be a non-empty string.")
                else:
                    normalized[name] = value.strip()

        if "line_ids" in normalized and normalized["line_ids"] is not None:
            lines, line_error = _normalize_line_ids(normalized["line_ids"])
            if line_error:
                errors.append(line_error)
            else:
                normalized["line_ids"] = lines

        for name in ("station_ids", "error_ids", "incident_ids"):
            if name in normalized and normalized[name] is not None:
                values, list_error = _normalize_string_list(normalized[name], name)
                if list_error:
                    errors.append(list_error)
                else:
                    normalized[name] = values

        parsed_dates: dict[str, datetime] = {}
        for name in ("date_from", "date_to"):
            if name in normalized and normalized[name] is not None:
                parsed, date_error = _parse_datetime(normalized[name], name)
                if date_error:
                    errors.append(date_error)
                elif parsed is not None:
                    parsed_dates[name] = parsed
                    normalized[name] = str(normalized[name]).strip()

        if "date_from" in parsed_dates and "date_to" in parsed_dates:
            start = parsed_dates["date_from"]
            end = parsed_dates["date_to"]
            if tool in {
                ToolName.GET_PRODUCTION_STATISTICS,
                ToolName.CALCULATE_PRODUCTION_IMPACT,
            }:
                if end <= start:
                    errors.append("date_to must be later than date_from.")
            elif end < start:
                errors.append("date_to must not be earlier than date_from.")

        if tool in {
            ToolName.GET_PRODUCTION_STATISTICS,
            ToolName.CALCULATE_PRODUCTION_IMPACT,
        } and normalized.get("line_ids") == []:
            errors.append("line_ids must contain at least one line.")

        return normalized, errors

    def _clarification_response(
        self,
        state: AgentState,
        reason: str,
        *,
        partial_arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Expose validation outcome as state; RESPONSE owns all user-facing text."""
        attempts = int(state.get("clarification_attempts", 0)) + 1
        exhausted = attempts >= MAX_ARGUMENT_ATTEMPTS

        return {
            "phase": Phase.RESET if exhausted else Phase.WAITING_FOR_INPUT,
            "pending_interaction": (
                PendingInteraction.NONE
                if exhausted
                else PendingInteraction.ARGUMENT_CLARIFICATION
            ),
            "clarification_attempts": attempts,
            "current_tool_arguments": partial_arguments,
            "response_payload": {
                "kind": "argument_resolver",
                "data": {"issues": [reason]},
            },
        }

    @staticmethod
    def _ready_update(
        tool: ToolName,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "phase": Phase.TOOL_READY,
            "pending_interaction": PendingInteraction.NONE,
            "clarification_attempts": 0,
            "current_tool": tool,
            "current_tool_arguments": arguments,
            "response_payload": None,
        }

    @staticmethod
    def _focus_updates(arguments: dict[str, Any]) -> dict[str, Any]:
        updates: dict[str, Any] = {}

        line_ids = arguments.get("line_ids")
        if isinstance(line_ids, list):
            updates["selected_line_ids"] = list(line_ids)

        if arguments.get("error_id"):
            updates["selected_error_ids"] = [str(arguments["error_id"])]
        elif isinstance(arguments.get("error_ids"), list):
            updates["selected_error_ids"] = list(arguments["error_ids"])

        if arguments.get("incident_id"):
            updates["selected_incident_ids"] = [str(arguments["incident_id"])]
        elif isinstance(arguments.get("incident_ids"), list):
            updates["selected_incident_ids"] = list(arguments["incident_ids"])

        if arguments.get("date_from") and arguments.get("date_to"):
            updates["selected_date_range"] = {
                "date_from": str(arguments["date_from"]),
                "date_to": str(arguments["date_to"]),
            }

        return updates


def _normalize_line_ids(value: Any) -> tuple[list[int], str | None]:
    if not isinstance(value, list):
        return [], "line_ids must be a list such as [1] or [1, 2]."

    normalized: list[int] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int):
            return [], "line_ids may contain only integer values 1 through 4."
        if item not in VALID_LINE_IDS:
            return [], "line_ids may contain only values 1 through 4."
        if item not in normalized:
            normalized.append(item)
    return normalized, None


def _normalize_string_list(
    value: Any,
    field_name: str,
) -> tuple[list[str], str | None]:
    if not isinstance(value, list):
        return [], f"{field_name} must be a list of strings."

    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            return [], f"{field_name} must contain only non-empty strings."
        clean_item = item.strip()
        if clean_item not in normalized:
            normalized.append(clean_item)
    return normalized, None


def _parse_datetime(
    value: Any,
    field_name: str,
) -> tuple[datetime | None, str | None]:
    if not isinstance(value, str) or not value.strip():
        return None, f"{field_name} must be an ISO-8601 datetime string."
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None, f"{field_name} must be a valid ISO-8601 datetime."
    if parsed.tzinfo is not None:
        return (
            None,
            f"{field_name} must be timezone-naive like the MES simulated time.",
        )
    return parsed, None
