"""Resolve ProductionAgent arguments through two reusable LLM prompt profiles.

The agent owns LLM interaction only. It routes each selected tool to the shared
argument Selector, the shared argument Synthesizer, or both. Shared operational
knowledge for the selected MCP tool is discovered at runtime and supplied
through AgentPrompt dynamic bindings. Tool-specific validation, defaults,
clarification state, and response text remain outside this module.

Main classes:
    ArgumentResolverAgent:
        Runs the reusable argument LLM profiles for one selected MCP tool.

Main methods:
    resolve():
        Returns extracted argument candidates for deterministic validation.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import sys
from typing import Any, Optional

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


class ArgumentResolverAgent:
    """Extract candidate arguments without enforcing tool-specific rules."""

    def __init__(self, mcp_client: ShopfloorMcpClient | None = None) -> None:
        self._factory = AgentFactory(agents_root=AGENTS_ROOT)
        self._selector_prompt = self._factory.get_agent(
            "argument_resolver",
            "ArgumentSelectorAgent",
        )
        self._synthesizer_prompt = self._factory.get_agent(
            "argument_resolver",
            "ArgumentSynthesizerAgent",
        )
        self._selector_llm = LLMClient()
        self._synthesizer_llm = LLMClient()
        self._mcp = mcp_client or get_default_client()

    def resolve(
        self,
        tool_name: ToolName,
        user_request: str,
        reference_datetime: Optional[str] = None,
        previous_context: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Extract candidate arguments using the routing agreed for each tool."""
        if tool_name == ToolName.GET_STATUS:
            return {}

        try:
            discovery = self._mcp.discovery_context()
            selected_tool_context = self._mcp.selected_tool_context(tool_name.value)
        except Exception as exc:
            LOGGER.developer("argument_resolver_mcp.error", locals())
            return {}

        mcp_server_instructions = discovery["server_instructions"]

        if tool_name == ToolName.GET_RESOLUTION_INSTRUCTIONS:
            return self._select(
                user_request,
                tool_name,
                previous_context,
                mcp_server_instructions,
                selected_tool_context,
            )

        if tool_name == ToolName.GET_INCIDENT_DETAILS:
            return self._synthesize(
                user_request,
                tool_name,
                reference_datetime,
                previous_context,
                mcp_server_instructions,
                selected_tool_context,
            )

        return asyncio.run(
            self._resolve_both(
                user_request,
                tool_name,
                reference_datetime,
                previous_context,
                mcp_server_instructions,
                selected_tool_context,
            )
        )

    async def _resolve_both(
        self,
        user_request: str,
        tool_name: ToolName,
        reference_datetime: Optional[str],
        previous_context: Optional[dict[str, Any]],
        mcp_server_instructions: str,
        selected_tool_context: str,
    ) -> dict[str, Any]:
        selector_task = asyncio.to_thread(
            self._select,
            user_request,
            tool_name,
            previous_context,
            mcp_server_instructions,
            selected_tool_context,
        )
        synthesizer_task = asyncio.to_thread(
            self._synthesize,
            user_request,
            tool_name,
            reference_datetime,
            previous_context,
            mcp_server_instructions,
            selected_tool_context,
        )
        selector_result, synthesizer_result = await asyncio.gather(
            selector_task,
            synthesizer_task,
        )
        return {**selector_result, **synthesizer_result}

    def _select(
        self,
        user_request: str,
        tool_name: ToolName,
        previous_context: Optional[dict[str, Any]],
        mcp_server_instructions: str,
        selected_tool_context: str,
    ) -> dict[str, Any]:
        payload = {
            "mcp_server_instructions": mcp_server_instructions,
            "mcp_selected_tool_context": selected_tool_context,
            "tool_name": tool_name.value,
            "user_request": str(user_request or "").strip(),
        }
        parsed = self._call_prompt(
            prompt=self._selector_prompt,
            llm=self._selector_llm,
            payload=payload,
            log_prefix="argument_selector_llm",
            previous_context=previous_context,
        )

        line_ids = parsed.get("line_ids")
        if isinstance(line_ids, list):
            parsed["line_ids"] = [
                int(value)
                for value in line_ids
                if isinstance(value, str) and value.isdigit()
            ]
        return parsed

    def _synthesize(
        self,
        user_request: str,
        tool_name: ToolName,
        reference_datetime: Optional[str],
        previous_context: Optional[dict[str, Any]],
        mcp_server_instructions: str,
        selected_tool_context: str,
    ) -> dict[str, Any]:
        payload = {
            "mcp_server_instructions": mcp_server_instructions,
            "mcp_selected_tool_context": selected_tool_context,
            "tool_name": tool_name.value,
            "reference_datetime": reference_datetime,
            "user_request": str(user_request or "").strip(),
        }
        parsed = self._call_prompt(
            prompt=self._synthesizer_prompt,
            llm=self._synthesizer_llm,
            payload=payload,
            log_prefix="argument_synthesizer_llm",
            previous_context=previous_context,
        )

        incident_ids = parsed.get("incident_ids")
        if isinstance(incident_ids, str) and incident_ids.strip():
            parsed["incident_ids"] = [incident_ids.strip()]
        elif isinstance(incident_ids, list):
            normalized: list[str] = []
            for value in incident_ids:
                if not isinstance(value, str) or not value.strip():
                    continue
                clean_value = value.strip()
                if clean_value not in normalized:
                    normalized.append(clean_value)
            parsed["incident_ids"] = normalized or None
        return parsed

    @staticmethod
    def _call_prompt(
        *,
        prompt: Any,
        llm: LLMClient,
        payload: dict[str, Any],
        log_prefix: str,
        previous_context: Optional[dict[str, Any]],
    ) -> dict[str, Any]:
        messages, response_format = prompt.compose(payload)
        # Added on 16.09.2026: append RESPONSE-time context after static AgentPrompt composition.
        messages = append_previous_context_to_messages(messages, previous_context)
        LOGGER.developer(f"{log_prefix}.request", locals())

        try:
            response = llm.chat(
                messages=messages,
                model_name=prompt.model,
                temperature=prompt.temperature,
                max_output_tokens=prompt.max_tokens,
                response_format=response_format,
                reasoning_effort=prompt.reasoning_effort,
                return_metadata=True,
                prompt_cache_key=prompt.prompt_cache_key,
            )
            raw_output = str(response.get("content") or "")
            parsed_output = prompt.parse(raw_output)
            LOGGER.developer(f"{log_prefix}.response", locals())
            return parsed_output
        except Exception as exc:
            LOGGER.developer(f"{log_prefix}.error", locals())
            return {}
