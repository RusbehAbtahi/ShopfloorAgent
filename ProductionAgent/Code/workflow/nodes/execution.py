"""Execute the selected Shopfloor tool through the ProductionAgent MCP client.

This node is intentionally deterministic and contains no LLM logic. It passes
the already validated tool name and arguments to the MCP client, receives the
unwrapped structured business dictionary, and preserves the exact successful
call in LangGraph evidence/history.

Main classes:
    ExecutionNode:
        Dispatches current_tool over MCP and records the returned evidence.

Main methods:
    run():
        Executes one validated MCP tool call and stores its raw result/history.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys
from typing import Any

from ..state import AgentState, Phase


_MCP_CLIENT_DIR = Path(__file__).resolve().parents[2] / "mcp"
if str(_MCP_CLIENT_DIR) not in sys.path:
    sys.path.insert(0, str(_MCP_CLIENT_DIR))

from client import ShopfloorMcpClient, get_default_client


class ExecutionNode:
    """Run one already validated deterministic MCP tool invocation."""

    def __init__(self, mcp_client: ShopfloorMcpClient | None = None) -> None:
        self._client = mcp_client or get_default_client()

    def run(self, state: AgentState) -> dict[str, Any]:
        """Execute current_tool and preserve the exact successful call in history."""
        if state["phase"] != Phase.TOOL_READY:
            raise RuntimeError("EXECUTION requires phase TOOL_READY.")

        current_tool = state.get("current_tool")
        arguments = state.get("current_tool_arguments")
        if current_tool is None or arguments is None:
            raise RuntimeError("EXECUTION requires a selected tool and arguments.")

        # 16.09.2026 - MCP wiring: execute Shopfloor tools through the MCP client.
        result = self._client.call_tool(current_tool.value, arguments)
        if not isinstance(result, dict):
            raise TypeError("Shopfloor MCP tools must return a dictionary result.")

        history = list(state.get("tool_history", []))
        history.append(
            {
                "tool_name": current_tool.value,
                "arguments": deepcopy(arguments),
                "result": deepcopy(result),
            }
        )

        return {
            "phase": Phase.TOOL_DONE,
            "current_tool_result": result,
            "tool_history": history,
        }
