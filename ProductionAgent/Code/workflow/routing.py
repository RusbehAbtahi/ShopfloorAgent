"""Own deterministic edge decisions for the ProductionAgent LangGraph.

The router contains no business processing. It reads node outcomes already
stored in AgentState and returns the name of the next graph node.

Main classes:
    GraphRouter:
        Maps REQUEST, SELECTOR, and ARGUMENT_RESOLVER outcomes to next nodes.

Main methods:
    after_request():
        Re-enters the correct node for fresh or pending user input.
    after_selector():
        Continues to argument resolution or returns a clarification response.
    after_argument_resolver():
        Continues to execution or returns an argument clarification response.
"""

from __future__ import annotations

from typing import Literal

from .state import AgentState, PendingInteraction, Phase


RequestRoute = Literal["selector", "argument_resolver", "post_processing"]
SelectorRoute = Literal["argument_resolver", "response"]
ArgumentRoute = Literal["execution", "response"]


class GraphRouter:
    """Keep conditional-edge decisions separate from graph construction."""

    def after_request(self, state: AgentState) -> RequestRoute:
        """Choose the re-entry node from the currently pending interaction."""
        pending = state["pending_interaction"]
        if pending == PendingInteraction.ARGUMENT_CLARIFICATION:
            # Added on 16.09.2026: re-check intent so a clear new request can escape the old clarification.
            return "selector"
        if pending == PendingInteraction.REPAIR_PRESENTATION:
            return "post_processing"
        return "selector"

    def after_selector(self, state: AgentState) -> SelectorRoute:
        """Continue only when SELECTOR produced a valid canonical tool."""
        if state["phase"] == Phase.TOOL_SELECTED:
            return "argument_resolver"
        return "response"

    def after_argument_resolver(self, state: AgentState) -> ArgumentRoute:
        """Execute only after arguments passed deterministic validation."""
        if state["phase"] == Phase.TOOL_READY:
            return "execution"
        return "response"
