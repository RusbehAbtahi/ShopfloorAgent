"""Focused regression tests for feedback changes added on 16.09.2026."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

CODE_DIR = Path(__file__).resolve().parents[1] / "Code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from workflow.nodes.helpers.argument_resolver_deterministic import DeterministicArgumentResolver
from workflow.nodes.helpers.response_helper import tool_result_markdown
from workflow.nodes.post_processing import PostProcessingNode
from workflow.nodes.selector import SelectorNode
from workflow.routing import GraphRouter
from workflow.previous_turn_context import build_previous_response_context, append_previous_context_to_messages
from workflow.state import PendingInteraction, Phase, ToolName


class FeedbackChangeTests(unittest.TestCase):
    """Verify approved date, context, and presentation behavior."""

    def setUp(self) -> None:
        self.resolver = DeterministicArgumentResolver()

    def test_production_statistics_without_date_needs_clarification(self) -> None:
        state = self._state(ToolName.GET_PRODUCTION_STATISTICS)
        update = self.resolver.resolve_extracted(state, {"line_ids": [1]})
        self.assertEqual(update["phase"], Phase.WAITING_FOR_INPUT)
        issue = update["response_payload"]["data"]["issues"][0]
        self.assertIn("requires a date/time scope", issue)

    def test_list_prior_incidents_without_dates_uses_full_history(self) -> None:
        state = self._state(ToolName.LIST_PRIOR_INCIDENTS)
        bounds = (
            datetime.fromisoformat("2026-09-10T08:00:00"),
            datetime.fromisoformat("2026-09-17T09:30:00"),
        )
        with patch(
            "workflow.nodes.helpers.argument_resolver_defaults._incident_history_bounds",
            return_value=bounds,
        ):
            update = self.resolver.resolve_extracted(state, {})
        arguments = update["current_tool_arguments"]
        self.assertEqual(update["phase"], Phase.TOOL_READY)
        self.assertEqual(arguments["date_from"], "2026-09-10T08:00:00")
        self.assertEqual(arguments["date_to"], "2026-09-17T09:30:00")

    def test_repair_experience_without_dates_uses_full_history(self) -> None:
        state = self._state(ToolName.GET_REPAIR_EXPERIENCE)
        bounds = (
            datetime.fromisoformat("2026-09-11T07:00:00"),
            datetime.fromisoformat("2026-09-17T09:30:00"),
        )
        with patch(
            "workflow.nodes.helpers.argument_resolver_defaults._repair_history_bounds",
            return_value=bounds,
        ):
            update = self.resolver.resolve_extracted(
                state,
                {"error_ids": ["S1_ALIGNMENT_FAILED"]},
            )
        arguments = update["current_tool_arguments"]
        self.assertEqual(update["phase"], Phase.TOOL_READY)
        self.assertEqual(arguments["date_from"], "2026-09-11T07:00:00")
        self.assertEqual(arguments["date_to"], "2026-09-17T09:30:00")

    def test_repair_backward_reference_reuses_single_previous_error(self) -> None:
        state = self._state(ToolName.GET_REPAIR_EXPERIENCE)
        state["current_request"] = "Can I have repaired details of this ?"
        state["previous_response_context"] = {
            "tool_name": "get_incident_details",
            "incident_ids": ["INC-000002"],
            "error_ids": ["S2_EARLY_TARGET_TORQUE"],
        }
        bounds = (
            datetime.fromisoformat("2026-09-13T12:41:43"),
            datetime.fromisoformat("2026-09-17T09:30:08"),
        )
        with patch(
            "workflow.nodes.helpers.argument_resolver_defaults._repair_history_bounds",
            return_value=bounds,
        ):
            update = self.resolver.resolve_extracted(
                state,
                {"line_ids": None, "station_ids": None, "error_ids": None},
            )
        self.assertEqual(update["phase"], Phase.TOOL_READY)
        self.assertEqual(
            update["current_tool_arguments"]["error_id"],
            "S2_EARLY_TARGET_TORQUE",
        )

    def test_impact_day_uses_complete_incident_calendar_day(self) -> None:
        state = self._state(ToolName.CALCULATE_PRODUCTION_IMPACT)
        state["current_request"] = "What impact had INC-000002 on impact day?"
        rows = [
            {
                "incident_id": "INC-000002",
                "occurrence_time": "2026-09-13T10:45:00",
                "repair_time": "2026-09-13T11:15:00",
                "status": "REPAIRED",
                "line_id": 1,
            }
        ]
        with patch(
            "workflow.nodes.helpers.argument_resolver_defaults._load_incident_rows",
            return_value=rows,
        ):
            update = self.resolver.resolve_extracted(
                state,
                {"incident_ids": ["INC-000002"]},
            )
        arguments = update["current_tool_arguments"]
        self.assertEqual(update["phase"], Phase.TOOL_READY)
        self.assertEqual(arguments["date_from"], "2026-09-13T00:00:00")
        self.assertEqual(arguments["date_to"], "2026-09-14T00:00:00")

    def test_production_statistics_whole_period_resolves_mes_bounds(self) -> None:
        state = self._state(ToolName.GET_PRODUCTION_STATISTICS)
        state["current_request"] = "Show production statistics for the whole period."
        start = datetime.fromisoformat("2026-09-10T08:00:00")
        last = datetime.fromisoformat("2026-09-16T18:00:00")
        current = datetime.fromisoformat("2026-09-17T09:30:00")
        with (
            patch(
                "workflow.nodes.helpers.argument_resolver_defaults._production_log_bounds",
                return_value=(start, last),
            ),
            patch(
                "workflow.nodes.helpers.argument_resolver_defaults._load_current_simulated_time",
                return_value=current,
            ),
        ):
            update = self.resolver.resolve_extracted(state, {})
        arguments = update["current_tool_arguments"]
        self.assertEqual(update["phase"], Phase.TOOL_READY)
        self.assertEqual(arguments["line_ids"], [1, 2, 3, 4])
        self.assertEqual(arguments["date_from"], "2026-09-10T08:00:00")
        self.assertEqual(arguments["date_to"], "2026-09-17T09:30:00")

    def test_previous_response_context_is_compact_and_semantic(self) -> None:
        state = self._state(ToolName.GET_INCIDENT_DETAILS)
        state["current_tool_arguments"] = {
            "incident_id": "INC-000002",
            "line_ids": [2],
            "date_from": "2026-09-13T00:00:00",
            "date_to": "2026-09-14T00:00:00",
        }
        state["current_tool_result"] = {
            "incident": {
                "incident_id": "INC-000002",
                "line_id": 2,
                "error_id": "S2_EARLY_TARGET_TORQUE",
            }
        }
        state["open_incidents"] = ["INC-OPEN-1"]
        context = build_previous_response_context(state)
        self.assertEqual(context["incident_ids"], ["INC-000002"])
        self.assertEqual(context["line_ids"], [2])
        self.assertNotIn("phase", context)
        self.assertNotIn("clarification_attempts", context)

        original = [
            {"role": "system", "content": "BASE"},
            {"role": "user", "content": "What impact did it have?"},
        ]
        augmented = append_previous_context_to_messages(original, context)
        self.assertEqual(original[0]["content"], "BASE")
        self.assertIn("Supplementary Previous-Turn Context", augmented[0]["content"])
        self.assertIn("INC-000002", augmented[0]["content"])
        self.assertIn("current user request is primary", augmented[0]["content"])

    def test_incident_detail_result_promotes_direct_followup_facts(self) -> None:
        state = self._state(ToolName.GET_INCIDENT_DETAILS)
        state["current_tool_arguments"] = {"incident_id": "INC-000002"}
        state["response_payload"] = {
            "kind": "tool_result",
            "data": {
                "incident": {
                    "incident_id": "INC-000002",
                    "line_id": 1,
                    "station": "Station 2",
                    "error_id": "S2_EARLY_TARGET_TORQUE",
                }
            },
        }
        context = build_previous_response_context(state)
        self.assertEqual(context["incident_ids"], ["INC-000002"])
        self.assertEqual(context["line_ids"], [1])
        self.assertEqual(context["station_ids"], ["Station 2"])
        self.assertEqual(context["error_ids"], ["S2_EARLY_TARGET_TORQUE"])

    def test_impact_snapshot_carries_forward_error_for_same_incident(self) -> None:
        state = self._state(ToolName.CALCULATE_PRODUCTION_IMPACT)
        state["current_tool_arguments"] = {
            "incident_ids": ["INC-000002"],
            "date_from": "2026-09-13T00:00:00",
            "date_to": "2026-09-14T00:00:00",
        }
        state["previous_response_context"] = {
            "tool_name": "get_incident_details",
            "incident_ids": ["INC-000002"],
            "error_ids": ["S2_EARLY_TARGET_TORQUE"],
        }
        state["response_payload"] = {"kind": "tool_result", "data": {"lines": []}}

        context = build_previous_response_context(state)
        self.assertEqual(context["error_ids"], ["S2_EARLY_TARGET_TORQUE"])

        state["current_tool_arguments"]["incident_ids"] = ["INC-000003"]
        changed_context = build_previous_response_context(state)
        self.assertNotIn("error_ids", changed_context)

    def test_argument_clarification_routes_back_through_selector(self) -> None:
        state = self._state(ToolName.GET_REPAIR_EXPERIENCE)
        state["pending_interaction"] = PendingInteraction.ARGUMENT_CLARIFICATION
        self.assertEqual(GraphRouter().after_request(state), "selector")

    def test_argument_clarification_can_switch_to_new_tool(self) -> None:
        node = SelectorNode.__new__(SelectorNode)
        node._deterministic = SimpleNamespace(select=lambda request: None)
        node._llm = SimpleNamespace(
            select=lambda request, **kwargs: ToolName.GET_INCIDENT_DETAILS
        )
        state = self._state(ToolName.GET_REPAIR_EXPERIENCE)
        state.update(
            {
                "pending_interaction": PendingInteraction.ARGUMENT_CLARIFICATION,
                "clarification_attempts": 2,
                "current_tool_arguments": {"date_from": "2026-09-13T00:00:00"},
                "previous_response_context": {"incident_ids": ["INC-000002"]},
            }
        )
        update = node.run(state)
        self.assertEqual(update["current_tool"], ToolName.GET_INCIDENT_DETAILS)
        self.assertIsNone(update["current_tool_arguments"])
        self.assertEqual(update["clarification_attempts"], 0)

    def test_unclear_argument_clarification_continues_same_tool_and_arguments(self) -> None:
        node = SelectorNode.__new__(SelectorNode)
        node._deterministic = SimpleNamespace(select=lambda request: None)
        node._llm = SimpleNamespace(select=lambda request, **kwargs: None)
        state = self._state(ToolName.GET_REPAIR_EXPERIENCE)
        state.update(
            {
                "pending_interaction": PendingInteraction.ARGUMENT_CLARIFICATION,
                "clarification_attempts": 1,
                "current_tool_arguments": {"date_from": "2026-09-13T00:00:00"},
            }
        )
        update = node.run(state)
        self.assertEqual(update["current_tool"], ToolName.GET_REPAIR_EXPERIENCE)
        self.assertEqual(update["current_tool_arguments"], state["current_tool_arguments"])
        self.assertEqual(update["clarification_attempts"], 1)

    def test_last_incident_request_displays_only_newest_matching_incident(self) -> None:
        state = self._state(ToolName.LIST_PRIOR_INCIDENTS)
        state["phase"] = Phase.TOOL_DONE
        state["current_request"] = "CAN you list the last incident"
        state["current_tool_result"] = {
            "incidents": [
                {"incident_id": "INC-000003", "line_id": 1},
                {"incident_id": "INC-000002", "line_id": 1},
            ]
        }
        update = PostProcessingNode().run(state)
        incidents = update["response_payload"]["data"]["incidents"]
        self.assertEqual([item["incident_id"] for item in incidents], ["INC-000003"])

    def test_impact_response_formats_scope_counts_duration_and_percent(self) -> None:
        data = {
            "lines": [
                {
                    "line_id": 1,
                    "downtime_seconds": 3725.4,
                    "projected_products": 2800.0,
                    "missed_products": 11.8,
                    "loss_percent": 20.0,
                }
            ],
            "total_projected_products": 2800.0,
            "total_missed_products": 11.8,
            "total_loss_percent": 20.0,
        }
        arguments = {
            "date_from": "2026-09-13T00:00:00",
            "date_to": "2026-09-14T00:00:00",
        }
        text = tool_result_markdown(
            data,
            tool=ToolName.CALCULATE_PRODUCTION_IMPACT,
            arguments=arguments,
        )
        self.assertIn("Effective Time Range", text)
        self.assertIn("2026-09-13T00:00:00", text)
        self.assertIn("2026-09-14T00:00:00", text)
        self.assertIn("1 hour 2 minutes 5 seconds", text)
        self.assertIn("Projected Products:** 2800", text)
        self.assertIn("Missed Products:** 12", text)
        self.assertIn("Loss Percent:** 20%", text)
        self.assertNotIn("2800.0", text)
        self.assertNotIn("11.8", text)

    @staticmethod
    def _state(tool: ToolName) -> dict:
        return {
            "phase": Phase.TOOL_SELECTED,
            "pending_interaction": PendingInteraction.NONE,
            "clarification_attempts": 0,
            "current_request": "natural language request",
            "current_tool": tool,
            "current_tool_arguments": None,
            "current_tool_result": None,
            "response_payload": None,
            "open_incidents": None,
        }


if __name__ == "__main__":
    unittest.main()
