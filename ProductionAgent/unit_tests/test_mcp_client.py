"""Focused tests for ProductionAgent MCP discovery, prompt binding, and execution."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


CODE_DIR = Path(__file__).resolve().parents[1] / "Code"
CLIENT_DIR = CODE_DIR / "mcp"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))
if str(CLIENT_DIR) not in sys.path:
    sys.path.insert(0, str(CLIENT_DIR))

from agent_stack.agent_factory import AgentFactory
from client import ShopfloorMcpClient
from workflow.nodes.execution import ExecutionNode
from workflow.state import Phase, ToolName


class ShopfloorMcpClientTests(unittest.TestCase):
    """Verify MCP metadata projection and structured-result compatibility."""

    def test_discovery_context_projects_server_and_tool_metadata(self) -> None:
        client = ShopfloorMcpClient("http://example.invalid/mcp")
        tools = {
            "get_status": {
                "name": "get_status",
                "title": "Status",
                "description": "Current status",
                "inputSchema": {"type": "object", "properties": {}},
                "outputSchema": {"type": "object"},
            }
        }
        with patch.object(
            client,
            "_discover_async",
            new=AsyncMock(return_value=("SERVER GUIDE", tools)),
        ):
            context = client.discovery_context()

        self.assertEqual(context["server_instructions"], "SERVER GUIDE")
        self.assertIn('"name": "get_status"', context["tool_catalog"])
        self.assertNotIn("outputSchema", context["tool_catalog"])
        self.assertIn(
            '"name": "get_status"',
            client.selected_tool_context("get_status"),
        )

    def test_call_tool_unwraps_structured_content(self) -> None:
        client = ShopfloorMcpClient("http://example.invalid/mcp")
        raw_result = SimpleNamespace(
            is_error=False,
            structured_content={"b_ok": True},
            content=[],
        )
        with patch.object(
            client,
            "_call_tool_async",
            new=AsyncMock(return_value=raw_result),
        ):
            result = client.call_tool("get_status", {})
        self.assertEqual(result, {"b_ok": True})

    def test_agent_json_places_mcp_context_in_system_prompt(self) -> None:
        factory = AgentFactory(agents_root=CODE_DIR / "agents" / "AgentJSON")
        selector = factory.get_agent("selector", "SelectorAgent")
        messages, _ = selector.compose(
            {
                "mcp_server_instructions": "SERVER GUIDE",
                "mcp_tool_catalog": "TOOL CATALOG",
                "user_request": "What is happening now?",
            }
        )
        self.assertIn("SERVER GUIDE", messages[0]["content"])
        self.assertIn("TOOL CATALOG", messages[0]["content"])
        self.assertIn("get_status", messages[0]["content"])

    def test_execution_node_uses_mcp_client_and_preserves_plain_dict(self) -> None:
        calls: list[tuple[str, dict]] = []

        class FakeClient:
            def call_tool(self, name: str, arguments: dict) -> dict:
                calls.append((name, dict(arguments)))
                return {"b_ok": True}

        node = ExecutionNode(mcp_client=FakeClient())  # type: ignore[arg-type]
        update = node.run(
            {
                "phase": Phase.TOOL_READY,
                "current_tool": ToolName.GET_STATUS,
                "current_tool_arguments": {},
                "tool_history": [],
            }
        )
        self.assertEqual(calls, [("get_status", {})])
        self.assertEqual(update["phase"], Phase.TOOL_DONE)
        self.assertEqual(update["current_tool_result"], {"b_ok": True})
        self.assertEqual(update["tool_history"][0]["result"], {"b_ok": True})


if __name__ == "__main__":
    unittest.main()
