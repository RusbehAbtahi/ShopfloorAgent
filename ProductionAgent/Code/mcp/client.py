

"""Consume the ShopfloorAgent MCP server from the synchronous ProductionAgent.

The client owns the MCP transport boundary only. It discovers server
instructions and tool metadata for prompt dynamic bindings, executes tools over
Streamable HTTP, and unwraps MCP structuredContent back to the plain dictionary
shape already consumed by LangGraph. The rest of ProductionAgent remains
synchronous and MCP-agnostic.

Main classes:
    ShopfloorMcpClient:
        Provides synchronous discovery and tool-call operations over MCP.

Main functions:
    get_default_client():
        Returns the process-shared Shopfloor MCP client instance.

Important notes:
    ProductionAgent already has a local package named ``mcp``. This module is
    imported as top-level ``client`` by its consumers; during SDK import the
    ProductionAgent Code directory is temporarily removed from sys.path so the
    installed official ``mcp`` package is resolved unambiguously.
"""

from __future__ import annotations

import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
from typing import Any


_CODE_DIR = Path(__file__).resolve().parents[1]
_REMOVED_PATHS: list[tuple[int, str]] = []
for index in range(len(sys.path) - 1, -1, -1):
    raw_path = sys.path[index]
    candidate = Path(raw_path or os.getcwd()).resolve()
    if candidate == _CODE_DIR:
        _REMOVED_PATHS.append((index, sys.path.pop(index)))
try:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
finally:
    for index, raw_path in reversed(_REMOVED_PATHS):
        sys.path.insert(index, raw_path)


DEFAULT_SERVER_URL = "http://127.0.0.1:8001/mcp"


class ShopfloorMcpClient:
    """Expose synchronous Shopfloor MCP discovery and execution to LangGraph."""

    def __init__(self, server_url: str | None = None) -> None:
        url = str(server_url or os.getenv("SHOPFLOOR_MCP_URL", DEFAULT_SERVER_URL)).strip()
        if not url:
            raise ValueError("Shopfloor MCP server URL must not be empty.")
        self._server_url = url
        self._server_instructions: str | None = None
        self._tools: dict[str, dict[str, Any]] = {}

    def discovery_context(self) -> dict[str, str]:
        """Return server guidance and the discovered tool catalog for prompts."""
        self._ensure_discovered()
        catalog = [self._prompt_tool_metadata(item) for item in self._tools.values()]
        return {
            "server_instructions": self._server_instructions or "",
            "tool_catalog": json.dumps(catalog, ensure_ascii=False, indent=2),
        }

    def selected_tool_context(self, tool_name: str) -> str:
        """Return one selected tool's MCP metadata for argument prompts."""
        self._ensure_discovered()
        metadata = self._tools.get(str(tool_name))
        if metadata is None:
            raise RuntimeError(f"Shopfloor MCP tool is not available: {tool_name}")
        return json.dumps(
            self._prompt_tool_metadata(metadata),
            ensure_ascii=False,
            indent=2,
        )

    def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Call one MCP tool and return its structured business dictionary."""
        result = asyncio.run(
            self._call_tool_async(
                str(tool_name),
                deepcopy(arguments or {}),
            )
        )
        if result.is_error:
            raise RuntimeError(self._result_text(result) or "Shopfloor MCP tool failed")
        structured = result.structured_content
        if not isinstance(structured, dict):
            raise RuntimeError("Shopfloor MCP tool returned no structured object.")
        return deepcopy(structured)

    def _ensure_discovered(self) -> None:
        if self._tools:
            return
        instructions, tools = asyncio.run(self._discover_async())
        self._server_instructions = instructions
        self._tools = tools

    async def _discover_async(self) -> tuple[str, dict[str, dict[str, Any]]]:
        async with streamable_http_client(self._server_url) as (
            read_stream,
            write_stream,
        ):
            async with ClientSession(read_stream, write_stream) as session:
                initialization = await session.initialize()
                tools_result = await session.list_tools()
                tools = {
                    tool.name: tool.model_dump(
                        by_alias=True,
                        mode="json",
                        exclude_none=True,
                    )
                    for tool in tools_result.tools
                }
                return str(initialization.instructions or ""), tools

    async def _call_tool_async(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> Any:
        async with streamable_http_client(self._server_url) as (
            read_stream,
            write_stream,
        ):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                return await session.call_tool(tool_name, arguments=arguments)

    @staticmethod
    def _prompt_tool_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
        """Project discovery metadata to the model-facing MCP contract."""
        return {
            key: deepcopy(metadata[key])
            for key in ("name", "title", "description", "inputSchema")
            if key in metadata
        }

    @staticmethod
    def _result_text(result: Any) -> str:
        texts: list[str] = []
        for item in result.content:
            text = getattr(item, "text", None)
            if isinstance(text, str) and text.strip():
                texts.append(text.strip())
        return "\n".join(texts)


_DEFAULT_CLIENT: ShopfloorMcpClient | None = None


def get_default_client() -> ShopfloorMcpClient:
    """Return one process-shared client without changing graph composition."""
    global _DEFAULT_CLIENT
    if _DEFAULT_CLIENT is None:
        _DEFAULT_CLIENT = ShopfloorMcpClient()
    return _DEFAULT_CLIENT
