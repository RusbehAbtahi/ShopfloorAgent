"""Unit tests for deterministic production statistics."""

from __future__ import annotations

from support import ShopfloorToolTestCase
from get_production_statistics import GetProductionStatisticsTool


class GetProductionStatisticsToolTests(ShopfloorToolTestCase):
    """Cover line selections, time boundaries, and request validation."""

    def test_one_two_three_and_four_line_selections(self) -> None:
        tool = GetProductionStatisticsTool(self.data_dir)
        cases = [
            ([1], [2], 2),
            ([1, 2], [2, 1], 3),
            ([1, 2, 3], [2, 1, 2], 5),
            ([1, 2, 3, 4], [2, 1, 2, 2], 7),
        ]

        for line_ids, expected_counts, expected_total in cases:
            with self.subTest(line_ids=line_ids):
                result = tool.execute(
                    "2026-09-13T10:00:00.000",
                    "2026-09-13T11:00:00.000",
                    line_ids,
                )
                self.assertEqual(
                    [item["completed_products"] for item in result["lines"]],
                    expected_counts,
                )
                self.assertEqual(
                    result["total_completed_products"],
                    expected_total,
                )

    def test_preserves_selection_order_and_removes_duplicates(self) -> None:
        result = GetProductionStatisticsTool(self.data_dir).execute(
            "2026-09-13T10:00:00.000",
            "2026-09-13T11:00:00.000",
            [4, 2, 4],
        )

        self.assertEqual(
            [item["line_id"] for item in result["lines"]],
            [4, 2],
        )

    def test_date_boundaries_are_inclusive_and_rate_uses_window_length(self) -> None:
        result = GetProductionStatisticsTool(self.data_dir).execute(
            "2026-09-13T10:00:00.000",
            "2026-09-13T10:30:00.000",
            [1, 2, 3],
        )

        self.assertEqual(
            [item["completed_products"] for item in result["lines"]],
            [2, 1, 1],
        )
        self.assertEqual(
            [item["production_rate_per_hour"] for item in result["lines"]],
            [4.0, 2.0, 2.0],
        )

    def test_missing_log_returns_zero_counts(self) -> None:
        (self.data_dir / "logs" / "production.log").unlink()

        result = GetProductionStatisticsTool(self.data_dir).execute(
            "2026-09-13T10:00:00.000",
            "2026-09-13T11:00:00.000",
            [1, 4],
        )

        self.assertEqual(result["total_completed_products"], 0)
        self.assertEqual(
            [item["production_rate_per_hour"] for item in result["lines"]],
            [0.0, 0.0],
        )

    def test_rejects_empty_or_invalid_line_selection(self) -> None:
        tool = GetProductionStatisticsTool(self.data_dir)

        with self.assertRaises(ValueError):
            tool.execute(
                "2026-09-13T10:00:00.000",
                "2026-09-13T11:00:00.000",
                [],
            )
        with self.assertRaises(ValueError):
            tool.execute(
                "2026-09-13T10:00:00.000",
                "2026-09-13T11:00:00.000",
                [5],
            )

    def test_rejects_invalid_or_non_increasing_dates(self) -> None:
        tool = GetProductionStatisticsTool(self.data_dir)

        invalid_pairs = [
            ("bad-date", "2026-09-13T11:00:00.000"),
            ("2026-09-13T11:00:00.000", "2026-09-13T11:00:00.000"),
            ("2026-09-13T11:00:00.000", "2026-09-13T10:00:00.000"),
            (
                "2026-09-13T10:00:00+00:00",
                "2026-09-13T11:00:00+00:00",
            ),
        ]

        for date_from, date_to in invalid_pairs:
            with self.subTest(date_from=date_from, date_to=date_to):
                with self.assertRaises(ValueError):
                    tool.execute(date_from, date_to, [1])
