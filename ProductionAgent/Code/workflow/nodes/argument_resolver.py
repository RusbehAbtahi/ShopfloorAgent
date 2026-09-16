"""LangGraph ARGUMENT_RESOLVER node with deterministic-first LLM fallback.

The node owns workflow orchestration only. Exact Python-like calls are resolved
by the deterministic strategy first. Natural-language requests are passed to
ArgumentResolverAgent, then returned to the same deterministic layer for merge,
defaulting, validation, and clarification state.

Main classes:
    ArgumentResolverNode:
        Coordinates deterministic and LLM argument resolution.

Main methods:
    run():
        Produces semantic graph updates for the selected tool.
"""

from __future__ import annotations

from typing import Any

from agents.argument_resolver_agent import ArgumentResolverAgent
from app_logging.agent_logger import LOGGER

from ..state import AgentState
from .helpers.argument_resolver_defaults import current_mes_datetime
from .helpers.argument_resolver_deterministic import DeterministicArgumentResolver


class ArgumentResolverNode:
    """Resolve arguments while keeping state ownership outside the LLM agent."""

    def __init__(self) -> None:
        self._deterministic = DeterministicArgumentResolver()
        self._llm = ArgumentResolverAgent()

    def run(self, state: AgentState) -> dict[str, Any]:
        """Use deterministic resolution first and the LLM only for natural language."""
        deterministic_update = self._deterministic.run(state)
        if deterministic_update is not None:
            # Added on 16.09.2026: expose deterministic inputs in the normal log as well.
            LOGGER.normal(
                "Arguments resolved",
                strategy="deterministic",
                arguments=deterministic_update.get("current_tool_arguments"),
            )
            return deterministic_update

        current_tool = state.get("current_tool")
        if current_tool is None:
            return self._deterministic.resolve_extracted(state, {})

        extracted = self._llm.resolve(
            current_tool,
            str(state.get("current_request") or ""),
            reference_datetime=current_mes_datetime(),
            previous_context=state.get("previous_response_context"),
        )
        update = self._deterministic.resolve_extracted(state, extracted)
        # Added on 16.09.2026: keep normal logs concise while showing the resolved inputs.
        LOGGER.normal(
            "Arguments resolved",
            strategy="llm",
            tool=current_tool.value,
            arguments=update.get("current_tool_arguments"),
        )
        return update
