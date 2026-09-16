"""Unit tests for the no-input Shopfloor status tool."""

from __future__ import annotations

from support import ShopfloorToolTestCase
from get_status import GetStatusTool


class GetStatusToolTests(ShopfloorToolTestCase):
    """Cover active incidents and all healthy-status branches."""

    def test_multiple_open_incidents_return_complete_details(self) -> None:
        result = GetStatusTool(self.data_dir).execute()

        self.assertFalse(result["b_ok"])
        self.assertEqual(
            [item["incident_id"] for item in result["incidents"]],
            ["INC-000005", "INC-000002"],
        )
        self.assertEqual(
            result["incidents"][0]["error_id"],
            "S2_EARLY_TARGET_TORQUE",
        )
        self.assertTrue(all("snapshot" not in item for item in result["incidents"]))
        self.assertTrue(all("measurements" not in item for item in result["incidents"]))

    def test_healthy_status_reports_fixed_last_hour_for_all_four_lines(self) -> None:
        self.close_open_incidents()

        result = GetStatusTool(self.data_dir).execute()

        self.assertTrue(result["b_ok"])
        self.assertEqual(result["last_incident_time"], "2026-09-13T10:50:00.000")
        self.assertEqual(
            [item["line_id"] for item in result["lines"]],
            [1, 2, 3, 4],
        )
        self.assertEqual(
            [item["completed_products_last_hour"] for item in result["lines"]],
            [2, 1, 2, 2],
        )
        self.assertEqual(
            [item["production_rate_per_hour"] for item in result["lines"]],
            [2.0, 1.0, 2.0, 2.0],
        )

    def test_healthy_status_without_incident_history_has_no_last_incident(self) -> None:
        self.clear_incidents()

        result = GetStatusTool(self.data_dir).execute()

        self.assertTrue(result["b_ok"])
        self.assertIsNone(result["last_incident_time"])

    def test_missing_runtime_time_returns_zero_healthy_statistics(self) -> None:
        self.close_open_incidents()
        self.write_runtime_state(None)

        result = GetStatusTool(self.data_dir).execute()

        self.assertTrue(result["b_ok"])
        self.assertEqual(
            [item["completed_products_last_hour"] for item in result["lines"]],
            [0, 0, 0, 0],
        )
        self.assertEqual(
            [item["production_rate_per_hour"] for item in result["lines"]],
            [0.0, 0.0, 0.0, 0.0],
        )

    def test_missing_runtime_state_file_is_handled_as_unknown_time(self) -> None:
        self.close_open_incidents()
        (self.data_dir / "runtime_state.json").unlink()

        result = GetStatusTool(self.data_dir).execute()

        self.assertTrue(result["b_ok"])
        self.assertEqual(len(result["lines"]), 4)
        self.assertTrue(
            all(item["completed_products_last_hour"] == 0 for item in result["lines"])
        )
