"""Focused tests for ProductionAgent argument selection and validation."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


CODE_DIR = Path(__file__).resolve().parents[1] / "Code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from agent_stack.agent_factory import AgentFactory
from workflow.nodes.helpers.argument_resolver_deterministic import (
    DeterministicArgumentResolver,
)
from workflow.state import PendingInteraction, Phase, ToolName


class ArgumentResolverTests(unittest.TestCase):
    """Cover reusable prompt parsing and deterministic tool-specific contracts."""

    @classmethod
    def setUpClass(cls) -> None:
        factory = AgentFactory(agents_root=CODE_DIR / "agents" / "AgentJSON")
        cls.selector_prompt = factory.get_agent(
            "argument_resolver",
            "ArgumentSelectorAgent",
        )
        cls.synthesizer_prompt = factory.get_agent(
            "argument_resolver",
            "ArgumentSynthesizerAgent",
        )

    def setUp(self) -> None:
        self.resolver = DeterministicArgumentResolver()

    def test_selector_prompt_accepts_multiple_enum_values_and_null(self) -> None:
        parsed = self.selector_prompt.parse(
            '{"line_ids":["1","3","4"],'
            '"station_ids":["Station 1","Station 2"],'
            '"error_ids":["S1_ALIGNMENT_FAILED","S3_FINAL_INSPECTION_FAILED"]}'
        )
        self.assertEqual(parsed["line_ids"], ["1", "3", "4"])
        self.assertEqual(parsed["station_ids"], ["Station 1", "Station 2"])
        self.assertEqual(
            parsed["error_ids"],
            ["S1_ALIGNMENT_FAILED", "S3_FINAL_INSPECTION_FAILED"],
        )
        self.assertEqual(
            self.selector_prompt.parse(
                '{"line_ids":null,"station_ids":null,"error_ids":null}'
            ),
            {"line_ids": None, "station_ids": None, "error_ids": None},
        )

    def test_selector_prompt_canonicalizes_valid_numeric_enum_ids(self) -> None:
        parsed = self.selector_prompt.parse(
            '{"line_ids":[2,true,5],"station_ids":null,"error_ids":null}'
        )
        self.assertEqual(parsed["line_ids"], ["2"])
        self.assertIsNone(parsed["station_ids"])
        self.assertIsNone(parsed["error_ids"])

    def test_synthesizer_prompt_preserves_incident_id_list(self) -> None:
        parsed = self.synthesizer_prompt.parse(
            '{"incident_ids":["INC-000001","INC-000003"],'
            '"date_from":"2026-09-13T10:00:00","date_to":null}'
        )
        self.assertEqual(parsed["incident_ids"], ["INC-000001", "INC-000003"])
        self.assertEqual(parsed["date_from"], "2026-09-13T10:00:00")
        self.assertIsNone(parsed["date_to"])

    def test_repair_experience_maps_one_error_and_rejects_many(self) -> None:
        state = self._state(ToolName.GET_REPAIR_EXPERIENCE)
        ready = self.resolver.resolve_extracted(
            state,
            {"error_ids": ["S1_ALIGNMENT_FAILED"]},
        )
        self.assertEqual(ready["phase"], Phase.TOOL_READY)
        self.assertEqual(
            ready["current_tool_arguments"]["error_id"],
            "S1_ALIGNMENT_FAILED",
        )

        clarification = self.resolver.resolve_extracted(
            state,
            {"error_ids": ["S1_ALIGNMENT_FAILED", "S2_EARLY_TARGET_TORQUE"]},
        )
        self.assertEqual(clarification["phase"], Phase.WAITING_FOR_INPUT)
        self.assertEqual(
            clarification["response_payload"]["data"]["issues"],
            ["get_repair_experience requires exactly one error_id."],
        )

    def test_null_llm_values_do_not_erase_retained_arguments(self) -> None:
        state = self._state(ToolName.LIST_PRIOR_INCIDENTS)
        state["current_tool_arguments"] = {"line_ids": [1]}
        update = self.resolver.resolve_extracted(
            state,
            {
                "line_ids": None,
                "station_ids": ["Station 2"],
                "error_ids": None,
                "date_from": None,
                "date_to": None,
            },
        )
        self.assertEqual(update["current_tool_arguments"]["line_ids"], [1])
        self.assertEqual(
            update["current_tool_arguments"]["station_ids"],
            ["Station 2"],
        )

    def test_missing_impact_ids_without_open_incidents_needs_clarification(self) -> None:
        state = self._state(ToolName.CALCULATE_PRODUCTION_IMPACT)
        with patch(
            "workflow.nodes.helpers.argument_resolver_defaults._load_open_incident_rows",
            return_value=[],
        ):
            update = self.resolver.resolve_extracted(state, {})
        self.assertEqual(update["phase"], Phase.WAITING_FOR_INPUT)
        self.assertIn(
            "Missing required argument: incident_ids.",
            update["response_payload"]["data"]["issues"][0],
        )

    def test_open_impact_fallback_preserves_user_dates_and_derives_incidents(self) -> None:
        state = self._state(ToolName.CALCULATE_PRODUCTION_IMPACT)
        open_rows = [
            {
                "incident_id": "INC-OPEN-1",
                "occurrence_time": "2026-09-17T09:00:00",
                "repair_time": None,
                "status": "OPEN",
                "line_id": 2,
            },
            {
                "incident_id": "INC-OPEN-2",
                "occurrence_time": "2026-09-17T09:10:00",
                "repair_time": None,
                "status": "OPEN",
                "line_id": 4,
            },
        ]
        with (
            patch(
                "workflow.nodes.helpers.argument_resolver_defaults._load_open_incident_rows",
                return_value=open_rows,
            ),
            patch(
                "workflow.nodes.helpers.argument_resolver_defaults._load_current_simulated_time",
                return_value=datetime.fromisoformat("2026-09-17T09:30:00"),
            ),
        ):
            update = self.resolver.resolve_extracted(
                state,
                {
                    "date_from": "2026-09-17T00:00:00",
                    "date_to": "2026-09-17T09:30:00",
                },
            )

        arguments = update["current_tool_arguments"]
        self.assertEqual(update["phase"], Phase.TOOL_READY)
        self.assertEqual(arguments["incident_ids"], ["INC-OPEN-1", "INC-OPEN-2"])
        self.assertEqual(arguments["line_ids"], [2, 4])
        self.assertEqual(arguments["date_from"], "2026-09-17T00:00:00")
        self.assertEqual(arguments["date_to"], "2026-09-17T09:30:00")

    @staticmethod
    def _state(tool: ToolName) -> dict:
        return {
            "phase": Phase.TOOL_SELECTED,
            "pending_interaction": PendingInteraction.NONE,
            "clarification_attempts": 0,
            "current_request": "natural language request",
            "current_tool": tool,
            "current_tool_arguments": None,
            "response_payload": None,
        }


if __name__ == "__main__":
    unittest.main()
