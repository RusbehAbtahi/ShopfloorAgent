"""Unit tests for deterministic prior-incident filtering."""

from __future__ import annotations

from support import ShopfloorToolTestCase
from list_prior_incidents import ListPriorIncidentsTool


class ListPriorIncidentsToolTests(ShopfloorToolTestCase):
    """Cover each optional filter, combinations, ordering, and validation."""

    def test_no_filters_returns_all_incidents_newest_first(self) -> None:
        result = ListPriorIncidentsTool(self.data_dir).execute()

        self.assertEqual(len(result["incidents"]), 6)
        self.assertEqual(result["incidents"][0]["incident_id"], "INC-000004")
        statuses = {
            item["incident_id"]: item["status"]
            for item in result["incidents"]
        }
        self.assertEqual(statuses["INC-000002"], "OPEN")
        self.assertEqual(statuses["INC-000001"], "CLOSED")

    def test_date_filters_individually_and_together(self) -> None:
        tool = ListPriorIncidentsTool(self.data_dir)

        from_only = tool.execute(date_from="2026-09-13T10:40:00.000")
        to_only = tool.execute(date_to="2026-09-13T10:10:00.000")
        both = tool.execute(
            date_from="2026-09-13T10:30:00.000",
            date_to="2026-09-13T10:45:00.000",
        )

        self.assertEqual(len(from_only["incidents"]), 3)
        self.assertEqual(len(to_only["incidents"]), 2)
        self.assertEqual(
            {item["incident_id"] for item in both["incidents"]},
            {"INC-000002", "INC-000003", "INC-000005"},
        )

    def test_one_two_three_and_four_line_filters(self) -> None:
        tool = ListPriorIncidentsTool(self.data_dir)
        cases = [
            ([1], {1}),
            ([1, 2], {1, 2}),
            ([1, 2, 3], {1, 2, 3}),
            ([1, 2, 3, 4], {1, 2, 3, 4}),
        ]

        for line_ids, expected_lines in cases:
            with self.subTest(line_ids=line_ids):
                result = tool.execute(line_ids=line_ids)
                self.assertTrue(result["incidents"])
                self.assertEqual(
                    {item["line_id"] for item in result["incidents"]},
                    expected_lines,
                )

    def test_station_and_error_filters_work_individually(self) -> None:
        tool = ListPriorIncidentsTool(self.data_dir)

        station_result = tool.execute(station_ids=["Station 1"])
        error_result = tool.execute(
            error_ids=["S3_FINAL_INSPECTION_FAILED"]
        )

        self.assertEqual(
            [item["incident_id"] for item in station_result["incidents"]],
            ["INC-000004"],
        )
        self.assertEqual(
            [item["incident_id"] for item in error_result["incidents"]],
            ["INC-000002"],
        )

    def test_all_filters_can_be_combined(self) -> None:
        result = ListPriorIncidentsTool(self.data_dir).execute(
            date_from="2026-09-13T10:00:00.000",
            date_to="2026-09-13T10:20:00.000",
            line_ids=[1, 2],
            station_ids=["Station 2"],
            error_ids=["S2_EARLY_TARGET_TORQUE"],
        )

        self.assertEqual(
            [item["incident_id"] for item in result["incidents"]],
            ["INC-000001", "INC-000006"],
        )

    def test_empty_filter_lists_are_unrestricted(self) -> None:
        result = ListPriorIncidentsTool(self.data_dir).execute(
            line_ids=[],
            station_ids=[],
            error_ids=[],
        )

        self.assertEqual(len(result["incidents"]), 6)

    def test_no_match_returns_empty_result(self) -> None:
        result = ListPriorIncidentsTool(self.data_dir).execute(
            station_ids=["Unknown Station"]
        )
        self.assertEqual(result, {"incidents": []})

    def test_rejects_invalid_filter_values_and_reversed_dates(self) -> None:
        tool = ListPriorIncidentsTool(self.data_dir)

        with self.assertRaises(ValueError):
            tool.execute(line_ids=[0])
        with self.assertRaises(ValueError):
            tool.execute(station_ids=[""])
        with self.assertRaises(ValueError):
            tool.execute(error_ids=["   "])
        with self.assertRaises(ValueError):
            tool.execute(
                date_from="2026-09-13T11:00:00.000",
                date_to="2026-09-13T10:00:00.000",
            )
