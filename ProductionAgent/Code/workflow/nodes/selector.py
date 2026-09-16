"""LangGraph SELECTOR node with deterministic-first and LLM-fallback selection."""

from __future__ import annotations

from typing import Any

from agents.selector_agent import SelectorAgent
from app_logging.agent_logger import LOGGER

from ..state import AgentState, PendingInteraction, Phase, ToolName
from .helpers.selector_deterministic import DeterministicSelector


MAX_SELECTOR_ATTEMPTS = 3


class SelectorNode:
    """Select one canonical tool and expose only semantic workflow state."""

    def __init__(self) -> None:
        self._deterministic = DeterministicSelector()
        self._llm = SelectorAgent()

    def run(self, state: AgentState) -> dict[str, Any]:
        """Use deterministic selection first and the LLM only as fallback."""
        request = str(state.get("current_request") or "")
        pending_tool = (
            state.get("current_tool")
            if state.get("pending_interaction") == PendingInteraction.ARGUMENT_CLARIFICATION
            else None
        )

        selected_tool = self._deterministic.select(request)
        strategy = "deterministic" if selected_tool is not None else "llm"
        if selected_tool is None:
            # Added on 16.09.2026: contextual follow-ups and clarification replacement are decided before argument resolution.
            selected_tool = self._llm.select(
                request,
                previous_context=state.get("previous_response_context"),
                pending_tool=pending_tool,
            )

        if pending_tool is not None:
            if selected_tool is None or selected_tool == pending_tool:
                LOGGER.normal(
                    "Argument clarification continues",
                    tool=pending_tool.value,
                    selector_result=selected_tool.value if selected_tool is not None else None,
                )
                return self._continued_argument_update(state, pending_tool)

            LOGGER.normal(
                "Argument clarification replaced",
                previous_tool=pending_tool.value,
                tool=selected_tool.value,
            )
            return self._selected_update(selected_tool)

        if selected_tool is not None:
            LOGGER.normal("Tool selected", strategy=strategy, tool=selected_tool.value)
            return self._selected_update(selected_tool)

        return self._clarification_update(state)


    @staticmethod
    def _continued_argument_update(state: AgentState, selected_tool: ToolName) -> dict[str, Any]:
        """Continue the same pending tool without discarding already resolved arguments."""
        return {
            "phase": Phase.TOOL_SELECTED,
            "pending_interaction": PendingInteraction.NONE,
            "clarification_attempts": int(state.get("clarification_attempts", 0)),
            "current_tool": selected_tool,
            "current_tool_arguments": state.get("current_tool_arguments"),
            "current_tool_result": None,
            "response_payload": None,
        }

    @staticmethod
    def _selected_update(selected_tool: ToolName) -> dict[str, Any]:
        return {
            "phase": Phase.TOOL_SELECTED,
            "pending_interaction": PendingInteraction.NONE,
            "clarification_attempts": 0,
            "current_tool": selected_tool,
            "current_tool_arguments": None,
            "current_tool_result": None,
            "response_payload": None,
        }

    @staticmethod
    def _clarification_update(state: AgentState) -> dict[str, Any]:
        attempts = int(state.get("clarification_attempts", 0)) + 1
        LOGGER.normal("Tool selection needs clarification", attempt=attempts)

        if attempts >= MAX_SELECTOR_ATTEMPTS:
            return {
                "phase": Phase.RESET,
                "pending_interaction": PendingInteraction.NONE,
                "clarification_attempts": attempts,
                "current_tool": None,
                "current_tool_arguments": None,
                "current_tool_result": None,
                "response_payload": {"kind": "selector"},
            }

        return {
            "phase": Phase.WAITING_FOR_INPUT,
            "pending_interaction": PendingInteraction.SELECTOR_CLARIFICATION,
            "clarification_attempts": attempts,
            "current_tool": None,
            "current_tool_arguments": None,
            "current_tool_result": None,
            "response_payload": {"kind": "selector"},
        }
