"""Focused tests for the ShopfloorAgent MCP application contract."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest


MCP_DIR = Path(__file__).resolve().parents[1]
if str(MCP_DIR) not in sys.path:
    sys.path.insert(0, str(MCP_DIR))

from mcp_app import SERVER_INSTRUCTIONS, ShopfloorMcpApplication


EXPECTED_TOOLS = [
    "get_status",
    "get_production_statistics",
    "list_prior_incidents",
    "get_resolution_instructions",
    "get_repair_experience",
    "calculate_production_impact",
    "get_incident_details",
]


class ShopfloorMcpApplicationTests(unittest.TestCase):
    """Verify discovery metadata and common MCP result behavior."""

    def setUp(self) -> None:
        self.application = ShopfloorMcpApplication()

    def test_lists_exactly_the_seven_canonical_tools(self) -> None:
        tools = self.application.list_tools()
        self.assertEqual([tool.name for tool in tools], EXPECTED_TOOLS)
        self.assertTrue(all(tool.description for tool in tools))
        self.assertTrue(all(tool.input_schema for tool in tools))

    def test_server_instructions_aggregate_global_and_tool_guidance(self) -> None:
        self.assertIn("Do not invent tool names", SERVER_INSTRUCTIONS)
        self.assertIn("get_repair_experience", SERVER_INSTRUCTIONS)
        self.assertIn("calculate_production_impact", SERVER_INSTRUCTIONS)

    def test_invalid_tool_arguments_return_standard_tool_error(self) -> None:
        result = self.application.call_tool("get_incident_details", {})
        self.assertTrue(result.is_error)
        self.assertIsInstance(result.structured_content, dict)
        self.assertIn("error", result.structured_content)


if __name__ == "__main__":
    unittest.main()
