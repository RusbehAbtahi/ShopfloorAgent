"""Implement the REQUEST entry and cross-turn re-entry behavior.

REQUEST does not interpret business intent. It marks the newest GUI input as
received, clears stale operation data, and preserves only the pending data that
is required to continue a clarification.

Main classes:
    RequestNode:
        Prepares AgentState before routing to the next business node.

Main methods:
    run():
        Applies fresh-request or clarification-continuation state transitions.
"""

from __future__ import annotations

import re
from typing import Any

from ..state import AgentState, PendingInteraction, Phase, ToolName


_TOOL_CALL_PATTERN = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*\(")


class RequestNode:
    """Prepare one user message for fresh selection or pending-work re-entry."""

    def run(self, state: AgentState) -> dict[str, Any]:
        """Mark input received and preserve only state needed by the next route."""
        request = str(state.get("current_request") or "").strip()
        pending = state["pending_interaction"]

        if pending == PendingInteraction.ARGUMENT_CLARIFICATION:
            return self._continue_argument_clarification(state, request)

        if pending == PendingInteraction.REPAIR_PRESENTATION:
            return self._continue_repair_presentation(state, request)

        if pending == PendingInteraction.SELECTOR_CLARIFICATION:
            return {
                "phase": Phase.INPUT_RECEIVED,
                "current_request": request,
                "current_tool": None,
                "current_tool_arguments": None,
                "current_tool_result": None,
                "response_payload": None,
            }

        # A normal new operation keeps conversational focus/history but clears
        # fields that belong only to the previous tool invocation.
        return {
            "phase": Phase.INPUT_RECEIVED,
            "pending_interaction": PendingInteraction.NONE,
            "clarification_attempts": 0,
            "current_request": request,
            "current_tool": None,
            "current_tool_arguments": None,
            "current_tool_result": None,
            "response_payload": None,
        }

    def _continue_argument_clarification(
        self,
        state: AgentState,
        request: str,
    ) -> dict[str, Any]:
        explicit_tool = self._explicit_tool(request)
        current_tool = state.get("current_tool")

        # A different explicit canonical tool is a clear replacement request.
        # It abandons the pending arguments and returns to normal selection.
        if explicit_tool is not None and explicit_tool != current_tool:
            return {
                "phase": Phase.INPUT_RECEIVED,
                "pending_interaction": PendingInteraction.NONE,
                "clarification_attempts": 0,
                "current_request": request,
                "current_tool": None,
                "current_tool_arguments": None,
                "current_tool_result": None,
                "response_payload": None,
            }

        return {
            "phase": Phase.INPUT_RECEIVED,
            "current_request": request,
            "current_tool_result": None,
            "response_payload": None,
        }

    def _continue_repair_presentation(
        self,
        state: AgentState,
        request: str,
    ) -> dict[str, Any]:
        explicit_tool = self._explicit_tool(request)
        if explicit_tool is not None:
            return {
                "phase": Phase.INPUT_RECEIVED,
                "pending_interaction": PendingInteraction.NONE,
                "clarification_attempts": 0,
                "current_request": request,
                "current_tool": None,
                "current_tool_arguments": None,
                "current_tool_result": None,
                "response_payload": None,
            }

        return {
            "phase": Phase.INPUT_RECEIVED,
            "current_request": request,
            "response_payload": None,
        }

    @staticmethod
    def _explicit_tool(request: str) -> ToolName | None:
        match = _TOOL_CALL_PATTERN.match(request)
        if match is None:
            return None

        candidate = match.group(1)
        try:
            return ToolName(candidate)
        except ValueError:
            return None
