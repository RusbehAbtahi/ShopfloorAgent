"""LLM fallback that selects one canonical ProductionAgent tool.

The selector keeps its agent-specific decision contract in AgentJSON while
receiving shared Shopfloor MCP server guidance and the discovered tool catalog
through the existing dynamic-binding path.

Main classes:
    SelectorAgent:
        Resolves one semantic tool-selection request through the Agent Stack.

Main methods:
    select():
        Returns one validated canonical ToolName or None.
"""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

from agent_stack.agent_factory import AgentFactory
from agent_stack.llm_client import LLMClient
from app_logging.agent_logger import LOGGER
from workflow.previous_turn_context import append_previous_context_to_messages
from workflow.state import ToolName


AGENTS_ROOT = Path(__file__).resolve().parent / "AgentJSON"
_MCP_CLIENT_DIR = Path(__file__).resolve().parents[1] / "mcp"
if str(_MCP_CLIENT_DIR) not in sys.path:
    sys.path.insert(0, str(_MCP_CLIENT_DIR))

from client import ShopfloorMcpClient, get_default_client


class SelectorAgent:
    """Use the neutral Agent Stack plus MCP discovery for tool selection."""

    def __init__(self, mcp_client: ShopfloorMcpClient | None = None) -> None:
        self._factory = AgentFactory(agents_root=AGENTS_ROOT)
        self._prompt = self._factory.get_agent("selector", "SelectorAgent")
        self._llm = LLMClient()
        self._mcp = mcp_client or get_default_client()

    def select(
        self,
        user_request: str,
        previous_context: dict[str, Any] | None = None,
        pending_tool: ToolName | None = None,
    ) -> ToolName | None:
        """Return one validated tool or None when the LLM cannot choose safely."""
        try:
            mcp_context = self._mcp.discovery_context()
            input_payload = {
                "mcp_server_instructions": mcp_context["server_instructions"],
                "mcp_tool_catalog": mcp_context["tool_catalog"],
                "user_request": str(user_request or "").strip(),
            }
            messages, response_format = self._prompt.compose(input_payload)
            # Added on 16.09.2026: append one RESPONSE-time context snapshot after static prompt composition.
            messages = append_previous_context_to_messages(messages, previous_context)
            # Added on 16.09.2026: tell the selector when this turn may either continue or replace an argument clarification.
            messages = self._append_pending_clarification(messages, pending_tool)
            LOGGER.developer("selector_llm.request", locals())

            response = self._llm.chat(
                messages=messages,
                model_name=self._prompt.model,
                temperature=self._prompt.temperature,
                max_output_tokens=self._prompt.max_tokens,
                response_format=response_format,
                reasoning_effort=self._prompt.reasoning_effort,
                return_metadata=True,
                prompt_cache_key=self._prompt.prompt_cache_key,
            )
            raw_output = str(response.get("content") or "")
            parsed_output = self._prompt.parse(raw_output)
            selected_tool = self._validated_tool(parsed_output.get("tool_name"))
            LOGGER.developer("selector_llm.response", locals())
            return selected_tool
        except Exception as exc:
            LOGGER.developer("selector_llm.error", locals())
            return None

    @staticmethod
    def _append_pending_clarification(
        messages: list[dict[str, str]],
        pending_tool: ToolName | None,
    ) -> list[dict[str, str]]:
        if pending_tool is None:
            return [dict(message) for message in messages]

        block = (
            "## Pending Argument Clarification\n"
            f"The previous turn is waiting for missing arguments for {pending_tool.value}. "
            "If the current message only supplies or clarifies information for that same operation, "
            f"select {pending_tool.value}. Select a different tool only when the current message clearly "
            "starts a different supported operation. The current user request remains authoritative."
        )
        copied = [dict(message) for message in messages]
        for message in copied:
            if str(message.get("role") or "").lower() == "system":
                current = str(message.get("content") or "").rstrip()
                message["content"] = f"{current}\n\n{block}" if current else block
                return copied
        copied.insert(0, {"role": "system", "content": block})
        return copied

    @staticmethod
    def _validated_tool(value: Any) -> ToolName | None:
        """Accept only canonical graph-owned tool names after LLM parsing."""
        if not isinstance(value, str):
            return None
        try:
            return ToolName(value)
        except ValueError:
            return None
