"""Shared isolated MES fixture for deterministic MCP tool unit tests.

The fixture recreates only the persisted MES contracts consumed by the
seven MCP tools: SQLite incidents, production log, runtime state, snapshots,
and the static error notebook.

Main classes:
    ShopfloorToolTestCase:
        Builds and cleans one temporary MES data directory per test.

Main methods:
    execute_sql():
        Applies a focused fixture mutation for one test.
    close_open_incidents():
        Converts all fixture OPEN incidents to REPAIRED.
    clear_incidents():
        Removes all fixture incidents.
    write_runtime_state():
        Replaces the persisted simulated plant time.
"""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest


MCP_DIR = Path(__file__).resolve().parents[1]
if str(MCP_DIR) not in sys.path:
    sys.path.insert(0, str(MCP_DIR))


class ShopfloorToolTestCase(unittest.TestCase):
    """Provide one deterministic, isolated MES persistence fixture."""

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temporary_directory.name)
        (self.data_dir / "logs").mkdir()
        (self.data_dir / "incident_snapshots").mkdir()

        self._create_database()
        self.write_runtime_state("2026-09-13T11:00:00.000")
        self._write_production_log()
        self._write_error_notebook()
        self._write_snapshots()
        self._insert_incidents()

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def execute_sql(
        self,
        statement: str,
        parameters: tuple[object, ...] = (),
     ) -> None:
        """Apply one explicit SQLite fixture mutation."""
        with sqlite3.connect(self.data_dir / "mes.sqlite") as connection:
            connection.execute(statement, parameters)

    def close_open_incidents(self) -> None:
        """Make the fixture healthy while preserving incident history."""
        self.execute_sql(
            """
            UPDATE incidents
            SET status = 'REPAIRED',
                repair_time = '2026-09-13T11:00:00.000',
                downtime_seconds = 60.0,
                repair_comment = COALESCE(repair_comment, 'Fixture repair')
            WHERE status = 'OPEN'
            """
        )

    def clear_incidents(self) -> None:
        """Remove all incident history from the fixture."""
        self.execute_sql("DELETE FROM incidents")

    def write_runtime_state(self, simulated_time: str | None) -> None:
        """Write the MES continuity timestamp used by status and impact."""
        state = {
            "schema_version": 1,
            "last_simulated_time": simulated_time,
            "product_numbers": {
                "1": 10,
                "2": 10,
                "3": 10,
                "4": 10,
            },
        }
        (self.data_dir / "runtime_state.json").write_text(
            json.dumps(state),
            encoding="utf-8",
        )

    def _create_database(self) -> None:
        with sqlite3.connect(self.data_dir / "mes.sqlite") as connection:
            connection.execute(
                """
                CREATE TABLE incidents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    incident_id TEXT UNIQU,
                    error_id TEXT NOT NULL,
                    error_message TEXT NOT NULL,
                    station TEXT NOT NULL,
                    line_id INTEGER NOT NULL,
                    product_number INTEGER NOT NULL,
                    occurrence_time TEXT NOT NULL,
                    repair_time TEXT,
                    downtime_seconds REAL,
                    status TEXT NOT NULL,
                    snapshot_path TEXT NOT NULL,
                    repair_comment TEXT,
                    measurements_json TEXT NOT NULL,
                    fault_sample_time_s REAL,
                    schema_version INTEGER NOT NULL
                )
                """
            )

    def _write_production_log(self) -> None:
        events = [
            "2026-09-13T09:59:00.000 | Line 1 | Product 0 | FINISHED",
            "2026-09-13T10:00:00.000 | Line 1 | Product 1 | FINISHED",
            "2026-09-13T10:10:00.000 | Line 1 | Product 2 | FINISHED",
            "2026-09-13T10:15:00.000 | Line 2 | Product 2 | START",
            "2026-09-13T10:20:00.000 | Line 2 | Product 1 | FINISHED",
            "2026-09-13T10:30:00.000 | Line 3 | Product 1 | FINISHED",
            "2026-09-13T10:40:00.000 | Line 3 | Product 2 | FINISHED",
            "2026-09-13T10:50:00.000 | Line 4 | Product 1 | FINISHED",
            "2026-09-13T11:00:00.000 | Line 4 | Product 2 | FINISHED",
            "malformed log line ignored by the parser",
        ]
        (self.data_dir / "logs" / "production.log").write_text(
            "\n".join(events) + "\n",
            encoding="utf-8",
        )

    def _write_error_notebook(self) -> None:
        notebook = {
            "schema_version": 1,
            "errors": {
                "S1_ALIGNMENT_FAILED": {
                    "meaning": "Alignment not confirmed.",
                    "likely_causes": ["Misalignment"],
                    "recommended_actions": ["Inspect alignment"],
                    "repair_confirmation": "All alignment sensors OK",
                },
                "S2_EARLY_TARGET_TORQUE": {
                    "meaning": "Target torque arrived too early.",
                    "likely_causes": ["Wrong screw"],
                    "recommended_actions": ["Inspect screw"],
                    "repair_confirmation": "Normal torque-angle behavior",
                },
                "S3_FINAL_INSPECTION_FAILED": {
                    "meaning": "Final inspection failed.",
                    "likely_causes": ["Assembly defect"],
                    "recommended_actions": ["Inspect final checks"],
                    "repair_confirmation": "All checks OK",
                },
            },
        }
        (self.data_dir / "error_notebook.json").write_text(
            json.dumps(notebook),
            encoding="utf-8",
        )

    def _write_snapshots(self) -> None:
        measurements = {
            "INC-000001": {"torque_nm": 12.0, "screw_angle_deg": 900.0},
            "INC-000002": {"st3_s1_check": 0},
            "INC-000003": {"torque_nm": 12.0, "screw_angle_deg": 1100.0},
            "INC-000004": {"st1_s3_alignment_ok": 0},
            "INC-000005": {"torque_nm": 12.0, "screw_angle_deg": 700.0},
            "INC-000006": {"torque_nm": 12.0, "screw_angle_deg": 1000.0},
        }
        for incident_id, values in measurements.items():
            snapshot = {
                "schema_version": 1,
                "incident_id": incident_id,
                "fault": {"measurements": values},
                "production_history": [],
            }
            path = (
                self.data_dir
                / "incident_snapshots"
                / f"{incident_id}.json"
            )
            path.write_text(json.dumps(snapshot), encoding="utf-8")

    def _insert_incidents(self) -> None:
        rows = [
            (
                "INC-000001",
                "S2_EARLY_TARGET_TORQUE",
                "Target torque reached too early",
                "Station 2",
                1,
                2,
                "2026-09-13T10:10:00.000",
                "2026-09-13T10:15:00.000",
                300.0,
                "REPAIRED",
                "incident_snapshots/INC-000001.json",
                "Replaced wrong screw",
                json.dumps({"torque_nm": 12.0, "screw_angle_deg": 900.0}),
                36.0,
                1,
            ),
            (
                "INC-000002",
                "S3_FINAL_INSPECTION_FAILED",
                "Final inspection failed",
                "Station 3",
                2,
                2,
                "2026-09-13T10:30:00.000",
                None,
                None,
                "OPEN",
                "incident_snapshots/INC-000002.json",
                None,
                json.dumps({"st3_s1_check": 0}),
                71.5,
                1,
            ),
            (
                "INC-000003",
                "S2_EARLY_TARGET_TORQUE",
                "Target torque reached too early",
                "Station 2",
                3,
                3,
                "2026-09-13T10:40:00.000",
                "2026-09-13T10:50:00.000",
                600.0,
                "REPAIRED",
                "incident_snapshots/INC-000003.json",
                "Cleaned damaged thread",
                json.dumps({"torque_nm": 12.0, "screw_angle_deg": 1100.0}),
                36.0,
                1,
            ),
            (
                "INC-000004",
                "S1_ALIGNMENT_FAILED",
                "Station 1 alignment failed",
                "Station 1",
                4,
                4,
                "2026-09-13T10:50:00.000",
                "2026-09-13T10:55:00.000",
                300.0,
                "REPAIRED",
                "incident_snapshots/INC-000004.json",
                "Repositioned assembly",
                json.dumps({"st1_s3_alignment_ok": 0}),
                11.5,
                1,
            ),
            (
                "INC-000005",
                "S2_EARLY_TARGET_TORQUE",
                "Target torque reached too early",
                "Station 2",
                4,
                5,
                "2026-09-13T10:45:00.000",
                None,
                None,
                "OPEN",
                "incident_snapshots/INC-000005.json",
                None,
                json.dumps({"torque_nm": 12.0, "screw_angle_deg": 700.0}),
                36.0,
                1,
            ),
            (
                "INC-000006",
                "S2_EARLY_TARGET_TORQUE",
                "Target torque reached too early",
                "Station 2",
                2,
                6,
                "2026-09-13T10:05:00.000",
                "2026-09-13T10:07:00.000",
                120.0,
                "REPAIRED",
                "incident_snapshots/INC-000006.json",
                "Changed screw type",
                json.dumps({"torque_nm": 12.0, "screw_angle_deg": 1000.0}),
                36.0,
                1,
            ),
        ]
        with sqlite3.connect(self.data_dir / "mes.sqlite") as connection:
            connection.executemany(
                """
                INSERT INTO incidents (
                    incident_id, error_id, error_message, station, line_id,
                    product_number, occurrence_time, repair_time,
                    downtime_seconds, status, snapshot_path, repair_comment,
                    measurements_json, fault_sample_time_s, schema_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
