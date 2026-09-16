"""Compose all user-facing ProductionAgent responses from semantic graph state."""

from __future__ import annotations

from typing import Any

from ..previous_turn_context import build_previous_response_context
from ..state import AgentState, PendingInteraction, Phase
from .helpers.response_helper import (
    argument_help_markdown,
    issues_markdown,
    load_response_json,
    tool_help_markdown,
    tool_result_markdown,
)


class ResponseNode:
    """Own response routing, template selection, and final Markdown composition."""

    def run(self, state: AgentState) -> dict[str, Any]:
        """Render the semantic response payload and close the current invocation."""
        payload = dict(state.get("response_payload") or {})
        kind = str(payload.get("kind") or "")
        response_text = self._render(state, kind, payload.get("data"))
        payload["text"] = response_text

        phase = self._response_phase(state)
        updates: dict[str, Any] = {
            "phase": phase,
            "response_payload": payload,
        }

        if phase not in {Phase.WAITING_FOR_INPUT, Phase.RESET}:
            updates["pending_interaction"] = PendingInteraction.NONE

        if phase == Phase.FINISHED:
            # Added on 16.09.2026: snapshot only a completed RESPONSE turn, never clarification/control state.
            updates["previous_response_context"] = build_previous_response_context(state)

        if phase != Phase.RESET:
            history = list(state.get("recent_history", []))
            history.append(
                {
                    "request": str(state.get("current_request") or ""),
                    "response": response_text,
                }
            )
            updates["recent_history"] = history[-2:]

        return updates

    def _render(self, state: AgentState, kind: str, data: Any) -> str:
        if kind == "selector":
            return self._render_selector(state)
        if kind == "argument_resolver":
            return self._render_argument_resolver(state, data)
        if kind == "tool_result":
            return self._render_tool_result(state, data)
        raise RuntimeError(f"RESPONSE received unsupported response kind: {kind!r}")

    @staticmethod
    def _render_selector(state: AgentState) -> str:
        config = load_response_json("selector")
        scenario = "reset" if state["phase"] == Phase.RESET else "clarification"
        template = str(config[scenario]["markdown"])
        return template.format(
            attempt=int(state.get("clarification_attempts", 0)),
            tool_help=tool_help_markdown(),
        )

    @staticmethod
    def _render_argument_resolver(state: AgentState, data: Any) -> str:
        config = load_response_json("argument_resolver")
        scenario = "reset" if state["phase"] == Phase.RESET else "clarification"
        template = str(config[scenario]["markdown"])
        current_tool = state.get("current_tool")
        return template.format(
            attempt=int(state.get("clarification_attempts", 0)),
            tool_name=current_tool.value if current_tool is not None else "unknown",
            issues=issues_markdown(data),
            argument_help=argument_help_markdown(current_tool),
        )

    @staticmethod
    def _render_tool_result(state: AgentState, data: Any) -> str:
        config = load_response_json("tool_result")
        template = str(config["success"]["markdown"])
        current_tool = state.get("current_tool")
        return template.format(
            tool_name=current_tool.value if current_tool is not None else "tool",
            result=tool_result_markdown(
                data,
                tool=current_tool,
                arguments=state.get("current_tool_arguments"),
            ),
        )

    @staticmethod
    def _response_phase(state: AgentState) -> Phase:
        if state["phase"] == Phase.RESET:
            return Phase.RESET
        if state["pending_interaction"] != PendingInteraction.NONE:
            return Phase.WAITING_FOR_INPUT
        return Phase.FINISHED
