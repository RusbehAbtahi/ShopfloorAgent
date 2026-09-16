"""Unit tests for deterministic production-impact calculation."""

from __future__ import annotations

from support import ShopfloorToolTestCase
from calculate_production_impact import CalculateProductionImpactTool


class CalculateProductionImpactToolTests(ShopfloorToolTestCase):
    """Cover incident selection, closed/open downtime, clipping, and validation."""

    def test_one_incident_uses_only_selected_incident_downtime(self) -> None:
        result = CalculateProductionImpactTool(self.data_dir).execute(
            ["INC-000001"],
            "2026-09-13T10:00:00.000",
            "2026-09-13T11:00:00.000",
            [1],
        )

        line = result["lines"][0]
        self.assertEqual(line["downtime_seconds"], 300.0)
        self.assertEqual(line["projected_products"], 40.0)
        self.assertEqual(line["missed_products"], 3.333)
        self.assertEqual(line["loss_percent"], 8.33)

    def test_multiple_incidents_across_lines_aggregate_correctly(self) -> None:
        tool = CalculateProductionImpactTool(self.data_dir)
        cases = [
            (["INC-000001", "INC-000006"], [1, 2], 420.0),
            (["INC-000001", "INC-000006", "INC-000003"], [1, 2, 3], 1020.0),
            (
                ["INC-000001", "INC-000006", "INC-000003", "INC-000005"],
                [1, 2, 3, 4],
                1920.0,
            ),
        ]

        for incident_ids, line_ids, expected_downtime in cases:
            with self.subTest(incident_ids=incident_ids, line_ids=line_ids):
                result = tool.execute(
                    incident_ids,
                    "2026-09-13T10:00:00.000",
                    "2026-09-13T11:00:00.000",
                    line_ids,
                )
                actual = sum(
                    item["downtime_seconds"] for item in result["lines"]
                )
                self.assertEqual(actual, expected_downtime)

    def test_open_incident_is_capped_at_current_simulated_time(self) -> None:
        result = CalculateProductionImpactTool(self.data_dir).execute(
            ["INC-000005"],
            "2026-09-13T10:00:00.000",
            "2026-09-13T12:00:00.000",
            [4],
        )

        self.assertEqual(result["lines"][0]["downtime_seconds"], 900.0)

    def test_window_clips_incident_start_and_end(self) -> None:
        result = CalculateProductionImpactTool(self.data_dir).execute(
            ["INC-000001"],
            "2026-09-13T10:12:00.000",
            "2026-09-13T10:14:00.000",
            [1],
        )

        self.assertEqual(result["lines"][0]["downtime_seconds"], 120.0)
        self.assertEqual(result["lines"][0]["loss_percent"], 100.0)

    def test_unselected_incidents_do_not_contribute(self) -> None:
        result = CalculateProductionImpactTool(self.data_dir).execute(
            ["INC-000004"],
            "2026-09-13T10:00:00.000",
            "2026-09-13T11:00:00.000",
            [1, 2, 3, 4],
        )

        downtimes = {
            item["line_id"]: item["downtime_seconds"]
            for item in result["lines"]
        }
        self.assertEqual(downtimes, {1: 0.0, 2: 0.0, 3: 0.0, 4: 300.0})

    def test_unknown_incident_returns_zero_loss(self) -> None:
        result = CalculateProductionImpactTool(self.data_dir).execute(
            ["INC-999999"],
            "2026-09-13T10:00:00.000",
            "2026-09-13T11:00:00.000",
            [1, 4],
        )

        self.assertEqual(result["total_missed_products"], 0.0)
        self.assertEqual(result["total_loss_percent"], 0.0)

    def test_duplicate_incidents_and_lines_are_removed(self) -> None:
        result = CalculateProductionImpactTool(self.data_dir).execute(
            ["INC-000001", "INC-000001"],
            "2026-09-13T10:00:00.000",
            "2026-09-13T11:00:00.000",
            [1, 1],
        )

        self.assertEqual(len(result["lines"]), 1)
        self.assertEqual(result["lines"][0]["line_id"], 1)
        self.assertEqual(result["lines"][0]["downtime_seconds"], 300.0)

    def test_rejects_invalid_required_inputs(self) -> None:
        tool = CalculateProductionImpactTool(self.data_dir)

        invalid_cases = [
            ([], "2026-09-13T10:00:00.000", "2026-09-13T11:00:00.000", [1]),
            ([""], "2026-09-13T10:00:00.000", "2026-09-13T11:00:00.000", [1]),
            (["INC-000001"], "2026-09-13T10:00:00.000", "2026-09-13T11:00:00.000", []),
            (["INC-000001"], "2026-09-13T10:00:00.000", "2026-09-13T11:00:00.000", [5]),
            (["INC-000001"], "2026-09-13T11:00:00.000", "2026-09-13T10:00:00.000", [1]),
            (["INC-000001"], "2026-09-13T11:00:00.000", "2026-09-13T11:00:00.000", [1]),
        ]

        for incident_ids, date_from, date_to, line_ids in invalid_cases:
            with self.subTest(
                incident_ids=incident_ids,
                date_from=date_from,
                date_to=date_to,
                line_ids=line_ids,
            ):
                with self.assertRaises(ValueError):
                    tool.execute(incident_ids, date_from, date_to, line_ids)
