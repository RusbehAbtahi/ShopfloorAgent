"""Unit tests for deterministic incident-detail retrieval."""

from __future__ import annotations

from support import ShopfloorToolTestCase
from get_incident_details import GetIncidentDetailsTool


class GetIncidentDetailsToolTests(ShopfloorToolTestCase):
    """Cover open/closed status, evidence, missing data, and validation."""

    def test_closed_incident_returns_stored_repair_and_evidence(self) -> None:
        result = GetIncidentDetailsTool(self.data_dir).execute("INC-000001")
        incident = result["incident"]

        self.assertEqual(incident["status"], "CLOSED")
        self.assertEqual(incident["downtime_seconds"], 300.0)
        self.assertEqual(
            incident["repair_comment"],
            "Replaced wrong screw",
        )
        self.assertEqual(incident["measurements"]["torque_nm"], 12.0)
        self.assertIsNotNone(incident["snapshot"])
        self.assertEqual(
            incident["detector_trigger_evidence"]["fault_sample_time_s"],
            36.0,
        )

    def test_open_incident_uses_current_simulated_time_for_downtime(self) -> None:
        result = GetIncidentDetailsTool(self.data_dir).execute("INC-000005")
        incident = result["incident"]

        self.assertEqual(incident["status"], "OPEN")
        self.assertEqual(incident["downtime_seconds"], 900.0)
        self.assertIsNone(incident["repair_time"])
        self.assertIsNone(incident["repair_comment"])

    def test_unknown_incident_returns_none(self) -> None:
        result = GetIncidentDetailsTool(self.data_dir).execute("INC-999999")
        self.assertEqual(result, {"incident": None})

    def test_missing_snapshot_is_reported_as_none_without_losing_incident(self) -> None:
        (
            self.data_dir
            / "incident_snapshots"
            / "INC-000001.json"
        ).unlink()

        result = GetIncidentDetailsTool(self.data_dir).execute("INC-000001")

        self.assertEqual(result["incident"]["incident_id"], "INC-000001")
        self.assertIsNone(result["incident"]["snapshot"])

    def test_open_incident_without_runtime_time_has_unknown_downtime(self) -> None:
        self.write_runtime_state(None)

        result = GetIncidentDetailsTool(self.data_dir).execute("INC-000002")

        self.assertIsNone(result["incident"]["downtime_seconds"])

    def test_rejects_blank_incident_id(self) -> None:
        with self.assertRaises(ValueError):
            GetIncidentDetailsTool(self.data_dir).execute(" ")

    def test_invalid_measurements_json_is_rejected(self) -> None:
        self.execute_sql(
            "UPDATE incidents SET measurements_json = ? WHERE incident_id = ?",
            ("not-json", "INC-000001"),
        )

        with self.assertRaises(ValueError):
            GetIncidentDetailsTool(self.data_dir).execute("INC-000001")

    def test_unsupported_mes_status_is_rejected(self) -> None:
        self.execute_sql(
            "UPDATE incidents SET status = ? WHERE incident_id = ?",
            ("UNKNOWN", "INC-000001"),
        )

        with self.assertRaises(ValueError):
            GetIncidentDetailsTool(self.data_dir).execute("INC-000001")
