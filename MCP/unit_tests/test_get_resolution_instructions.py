"""Unit tests for deterministic resolution instructions."""

from __future__ import annotations

from support import ShopfloorToolTestCase
from get_resolution_instructions import GetResolutionInstructionsTool


class GetResolutionInstructionsToolTests(ShopfloorToolTestCase):
    """Cover explicit error selection and automatic OPEN-error selection."""

    def test_omitted_error_ids_use_all_distinct_open_errors(self) -> None:
        result = GetResolutionInstructionsTool(self.data_dir).execute()

        self.assertEqual(
            [item["error_id"] for item in result["instructions"]],
            [
                "S2_EARLY_TARGET_TORQUE",
                "S3_FINAL_INSPECTION_FAILED",
            ],
        )

    def test_explicit_one_and_multiple_error_ids_preserve_order(self) -> None:
        tool = GetResolutionInstructionsTool(self.data_dir)

        single = tool.execute(["S1_ALIGNMENT_FAILED"])
        multiple = tool.execute(
            [
                "S3_FINAL_INSPECTION_FAILED",
                "S2_EARLY_TARGET_TORQUE",
            ]
        )

        self.assertEqual(
            [item["error_id"] for item in single["instructions"]],
            ["S1_ALIGNMENT_FAILED"],
        )
        self.assertEqual(
            [item["error_id"] for item in multiple["instructions"]],
            [
                "S3_FINAL_INSPECTION_FAILED",
                "S2_EARLY_TARGET_TORQUE",
            ],
        )

    def test_duplicates_are_removed_and_unknown_ids_are_skipped(self) -> None:
        result = GetResolutionInstructionsTool(self.data_dir).execute(
            [
                "S2_EARLY_TARGET_TORQUE",
                "S2_EARLY_TARGET_TORQUE",
                "UNKNOWN",
            ]
        )

        self.assertEqual(
            [item["error_id"] for item in result["instructions"]],
            ["S2_EARLY_TARGET_TORQUE"],
        )

    def test_explicit_empty_list_returns_empty_result(self) -> None:
        result = GetResolutionInstructionsTool(self.data_dir).execute([])
        self.assertEqual(result, {"instructions": []})

    def test_no_open_incidents_returns_empty_result_when_ids_omitted(self) -> None:
        self.close_open_incidents()

        result = GetResolutionInstructionsTool(self.data_dir).execute()

        self.assertEqual(result, {"instructions": []})

    def test_rejects_empty_error_id_value(self) -> None:
        with self.assertRaises(ValueError):
            GetResolutionInstructionsTool(self.data_dir).execute([""])

    def test_missing_notebook_returns_empty_result(self) -> None:
        (self.data_dir / "error_notebook.json").unlink()

        result = GetResolutionInstructionsTool(self.data_dir).execute(
            ["S2_EARLY_TARGET_TORQUE"]
        )

        self.assertEqual(result, {"instructions": []})
