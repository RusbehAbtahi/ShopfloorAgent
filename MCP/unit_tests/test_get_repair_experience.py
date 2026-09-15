"""Unit tests for raw historical repair experience."""

from __future__ import annotations

from support import ShopfloorToolTestCase
from get_repair_experience import GetRepairExperienceTool


class GetRepairExperienceToolTests(ShopfloorToolTestCase):
    """Cover date filters, line selections, repaired-only behavior, validation."""

    def test_required_error_id_returns_only_repaired_matching_cases(self) -> None:
        result = GetRepairExperienceTool(self.data_dir).execute(
            "S2_EARLY_TARGET_TORQUE"
        )

        self.assertEqual(
            [item["incident_id"] for item in result["experiences"]],
            ["INC-000003", "INC-000001", "INC-000006"],
        )

    def test_date_filters_individually_and_together(self) -> None:
        tool = GetRepairExperienceTool(self.data_dir)

        from_only = tool.execute(
            "S2_EARLY_TARGET_TORQUE",
            date_from="2026-09-13T10:10:00.000",
        )
        to_only = tool.execute(
            "S2_EARLY_TARGET_TORQUE",
            date_to="2026-09-13T10:10:00.000",
        )
        both = tool.execute(
            "S2_EARLY_TARGET_TORQUE",
            date_from="2026-09-13T10:06:00.000",
            date_to="2026-09-13T10:39:00.000",
        )

        self.assertEqual(
            [item["incident_id"] for item in from_only["experiences"]],
            ["INC-000003", "INC-000001"],
        )
        self.assertEqual(
            [item["incident_id"] for item in to_only["experiences"]],
            ["INC-000001", "INC-000006"],
        )
        self.assertEqual(
            [item["incident_id"] for item in both["experiences"]],
            ["INC-000001"],
        )

    def test_one_two_three_and_four_line_filters(self) -> None:
        tool = GetRepairExperienceTool(self.data_dir)
        cases = [
            ([1], {"INC-000001"}),
            ([1, 2], {"INC-000001", "INC-000006"}),
            ([1, 2, 3], {"INC-000001", "INC-000003", "INC-000006"}),
            ([1, 2, 3, 4], {"INC-000001", "INC-000003", "INC-000006"}),
        ]

        for line_ids, expected_ids in cases:
            with self.subTest(line_ids=line_ids):
                result = tool.execute(
                    "S2_EARLY_TARGET_TORQUE",
                    line_ids=line_ids,
                )
                self.assertEqual(
                    {item["incident_id"] for item in result["experiences"]},
                    expected_ids,
                )

    def test_combined_date_and_line_filters(self) -> None:
        result = GetRepairExperienceTool(self.data_dir).execute(
            "S2_EARLY_TARGET_TORQUE",
            date_from="2026-09-13T10:00:00.000",
            date_to="2026-09-13T10:20:00.000",
            line_ids=[2, 3],
        )

        self.assertEqual(
            [item["incident_id"] for item in result["experiences"]],
            ["INC-000006"],
        )

    def test_unknown_error_or_nonmatching_line_returns_empty_result(self) -> None:
        tool = GetRepairExperienceTool(self.data_dir)

        self.assertEqual(
            tool.execute("UNKNOWN"),
            {"experiences": []},
        )
        self.assertEqual(
            tool.execute("S2_EARLY_TARGET_TORQUE", line_ids=[4]),
            {"experiences": []},
        )

    def test_rejects_missing_error_invalid_line_and_reversed_dates(self) -> None:
        tool = GetRepairExperienceTool(self.data_dir)

        with self.assertRaises(ValueError):
            tool.execute(" ")
        with self.assertRaises(ValueError):
            tool.execute("S2_EARLY_TARGET_TORQUE", line_ids=[9])
        with self.assertRaises(ValueError):
            tool.execute(
                "S2_EARLY_TARGET_TORQUE",
                date_from="2026-09-13T11:00:00.000",
                date_to="2026-09-13T10:00:00.000",
            )
