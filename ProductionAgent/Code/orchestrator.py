"""Provide the stable GUI-facing entry point for the ProductionAgent workflow.

The orchestrator owns one compiled workflow graph and one session-level
AgentState. Each GUI request starts a new LangGraph invocation at START, while
unfinished clarification state is retained between invocations.

Main classes:
    ProductionAgentOrchestrator:
        Owns graph lifetime, session state, request execution, and full reset.

Main methods:
    run():
        Sends one user message through the graph and returns rendered text.
"""

from __future__ import annotations

from copy import deepcopy

from app_logging.agent_logger import LOGGER
from workflow.graph import ProductionAgentGraph
from workflow.state import AgentState, Phase, create_initial_state


class ProductionAgentOrchestrator:
    """Own the graph and persistent session state exposed to the Streamlit GUI."""

    def __init__(self) -> None:
        self._graph = ProductionAgentGraph()
        self._state: AgentState = create_initial_state()

    @property
    def state(self) -> AgentState:
        """Return a defensive copy for inspection without exposing mutable state."""
        return deepcopy(self._state)

    def run(self, user_input: str) -> str:
        """Run one user turn through LangGraph and return the rendered response."""
        request = str(user_input or "").strip()
        if not request:
            raise ValueError("ProductionAgent request must not be empty.")

        LOGGER.normal("Request received", request=request)
        invocation_state = deepcopy(self._state)
        invocation_state["current_request"] = request

        result = self._graph.invoke(invocation_state)
        payload = dict(result.get("response_payload") or {})
        response_text = str(payload.get("text") or "")

        # RESPONSE may render a reset explanation, but RESET itself must leave
        # no stale request, history, tool, or clarification data behind.
        if result.get("phase") == Phase.RESET:
            self._state = create_initial_state()
        else:
            self._state = result

        LOGGER.normal(
            "Response ready",
            kind=str(payload.get("kind") or ""),
            phase=str(result.get("phase") or ""),
        )
        return response_text
