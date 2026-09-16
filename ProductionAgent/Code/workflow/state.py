"""Define the shared state contract used by the ProductionAgent LangGraph.

This module owns only graph state types and deterministic reset defaults. Nodes
read and update these fields; routing uses them to decide which node runs next.

Main types:
    Phase:
        Identifies the current lifecycle phase of one graph operation.
    PendingInteraction:
        Identifies unfinished work that must continue on the next user turn.
    ToolName:
        Enumerates the seven canonical ShopfloorAgent tools.
    AgentState:
        Typed shared state passed between all LangGraph nodes.

Main functions:
    create_initial_state():
        Returns the exact RESET state used for a new or fully reset session.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, TypedDict


class Phase(str, Enum):
    """Lifecycle phases used to make graph progress explicit."""

    RESET = "RESET"
    WAITING_FOR_INPUT = "WAITING_FOR_INPUT"
    INPUT_RECEIVED = "INPUT_RECEIVED"
    TOOL_SELECTED = "TOOL_SELECTED"
    TOOL_READY = "TOOL_READY"
    TOOL_DONE = "TOOL_DONE"
    FINISHED = "FINISHED"
    FAILED = "FAILED"


class PendingInteraction(str, Enum):
    """Cross-turn work that determines where the next request must re-enter."""

    NONE = "NONE"
    SELECTOR_CLARIFICATION = "SELECTOR_CLARIFICATION"
    ARGUMENT_CLARIFICATION = "ARGUMENT_CLARIFICATION"
    REPAIR_PRESENTATION = "REPAIR_PRESENTATION"


class ToolName(str, Enum):
    """The seven deterministic tools supported by the ShopfloorAgent PoC."""

    GET_STATUS = "get_status"
    GET_PRODUCTION_STATISTICS = "get_production_statistics"
    LIST_PRIOR_INCIDENTS = "list_prior_incidents"
    GET_RESOLUTION_INSTRUCTIONS = "get_resolution_instructions"
    GET_REPAIR_EXPERIENCE = "get_repair_experience"
    CALCULATE_PRODUCTION_IMPACT = "calculate_production_impact"
    GET_INCIDENT_DETAILS = "get_incident_details"


class AgentState(TypedDict):
    """Shared mutable graph state for one session-level ProductionAgent workflow."""

    phase: Phase
    pending_interaction: PendingInteraction
    clarification_attempts: int

    current_request: str | None
    recent_history: list[dict[str, str]]

    current_tool: ToolName | None
    current_tool_arguments: dict[str, Any] | None
    current_tool_result: dict[str, Any] | None
    response_payload: dict[str, Any] | None

    tool_history: list[dict[str, Any]]

    open_incidents: list[str] | None
    selected_incident_ids: list[str]
    selected_line_ids: list[int]
    selected_error_ids: list[str]
    selected_date_range: dict[str, str] | None

    # Added on 16.09.2026: retain one compact RESPONSE-time context snapshot for follow-up LLM calls.
    previous_response_context: dict[str, Any] | None


def create_initial_state() -> AgentState:
    """Return the deterministic RESET state defined by the LangGraph baseline."""
    return {
        "phase": Phase.RESET,
        "pending_interaction": PendingInteraction.NONE,
        "clarification_attempts": 0,
        "current_request": None,
        "recent_history": [],
        "current_tool": None,
        "current_tool_arguments": None,
        "current_tool_result": None,
        "response_payload": None,
        "tool_history": [],
        "open_incidents": None,
        "selected_incident_ids": [],
        "selected_line_ids": [],
        "selected_error_ids": [],
        "selected_date_range": None,
        "previous_response_context": None,
    }
