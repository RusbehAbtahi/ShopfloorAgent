"""Persistent operational data for the Shopfloor MES.

The MES writes facts only:
- continuous runtime state;
- lightweight product START/FINISHED events;
- structured incidents in SQLite;
- incident evidence snapshots;
- timestamped history backups created by an explicit Reset History action.

All paths stored in SQLite are relative to ``data/`` so a backup can be restored
simply by copying its contents back into the active ``data/`` directory.
"""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import shutil
import sqlite3
import threading
from typing import Any


DATA_SCHEMA_VERSION = 1
DEFAULT_PRODUCT_NUMBERS = {str(line_id): 1 for line_id in range(1, 5)}


class MESDataStore:
    """Own the MES persistence layout and deterministic storage operations."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        self.db_path = self.data_dir / "mes.sqlite"
        self.runtime_state_path = self.data_dir / "runtime_state.json"
        self.logs_dir = self.data_dir / "logs"
        self.production_log_path = self.logs_dir / "production.log"
        self.snapshots_dir = self.data_dir / "incident_snapshots"
        self.backups_dir = self.data_dir / "history_backups"
        self._io_lock = threading.RLock()

    def initialize(self) -> None:
        """Create the active data layout and SQLite schema if missing."""
        with self._io_lock:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            self.logs_dir.mkdir(parents=True, exist_ok=True)
            self.snapshots_dir.mkdir(parents=True, exist_ok=True)
            self.backups_dir.mkdir(parents=True, exist_ok=True)
            self._initialize_database()
            if not self.runtime_state_path.exists():
                self._write_runtime_state(
                    {
                        "schema_version": DATA_SCHEMA_VERSION,
                        "last_simulated_time": None,
                        "product_numbers": DEFAULT_PRODUCT_NUMBERS.copy(),
                    }
                )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize_database(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS incidents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    incident_id TEXT UNIQUE,
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
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_incidents_error_id "
                "ON incidents(error_id)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_incidents_status "
                "ON incidents(status)"
            )

    def load_runtime_state(self) -> dict[str, Any]:
        """Return persisted simulation continuity state."""
        self.initialize()
        with self._io_lock:
            try:
                state = json.loads(self.runtime_state_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                state = {}

            product_numbers = state.get("product_numbers", {})
            normalized_products = {
                str(line_id): int(product_numbers.get(str(line_id), 1))
                for line_id in range(1, 5)
            }
            return {
                "schema_version": int(
                    state.get("schema_version", DATA_SCHEMA_VERSION)
                ),
                "last_simulated_time": state.get("last_simulated_time"),
                "product_numbers": normalized_products,
            }

    def get_resume_time(self) -> datetime | None:
        """Return the last persisted simulated plant time, if history exists."""
        value = self.load_runtime_state().get("last_simulated_time")
        if not value:
            return None
        return datetime.fromisoformat(str(value))

    def get_product_numbers(self) -> dict[int, int]:
        """Return current product numbers for the four lines."""
        state = self.load_runtime_state()
        return {
            line_id: int(state["product_numbers"].get(str(line_id), 1))
            for line_id in range(1, 5)
        }

    def save_runtime_state(
        self,
        simulated_time: datetime,
        product_numbers: dict[int, int],
    ) -> None:
        """Persist the continuity point used by every later Start."""
        with self._io_lock:
            self._write_runtime_state(
                {
                    "schema_version": DATA_SCHEMA_VERSION,
                    "last_simulated_time": simulated_time.isoformat(
                        timespec="milliseconds"
                    ),
                    "product_numbers": {
                        str(line_id): int(product_number)
                        for line_id, product_number in product_numbers.items()
                    },
                }
            )

    def _write_runtime_state(self, state: dict[str, Any]) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        temporary_path = self.runtime_state_path.with_suffix(".json.tmp")
        temporary_path.write_text(
            json.dumps(state, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        temporary_path.replace(self.runtime_state_path)

    def append_product_event(
        self,
        event: str,
        line_id: int,
        product_number: int,
        simulated_time: datetime,
    ) -> None:
        """Append one lightweight product lifecycle event to production.log."""
        event = event.upper()
        if event not in {"START", "FINISHED"}:
            raise ValueError(f"Unsupported product event: {event}")

        line = (
            f"{simulated_time.isoformat(timespec='milliseconds')} | "
            f"Line {line_id} | Product {product_number} | {event}\n"
        )
        with self._io_lock:
            self.logs_dir.mkdir(parents=True, exist_ok=True)
            with self.production_log_path.open("a", encoding="utf-8") as handle:
                handle.write(line)

    def create_incident(
        self,
        fault: Any,
        occurrence_time: datetime,
        history: list[dict[str, Any]],
    ) -> str:
        """Create one OPEN SQLite incident and its evidence snapshot."""
        self.initialize()
        measurements = dict(getattr(fault, "measurements", {}) or {})

        with self._io_lock, self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO incidents (
                    incident_id,
                    error_id,
                    error_message,
                    station,
                    line_id,
                    product_number,
                    occurrence_time,
                    repair_time,
                    downtime_seconds,
                    status,
                    snapshot_path,
                    repair_comment,
                    measurements_json,
                    fault_sample_time_s,
                    schema_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, 'OPEN', '', NULL, ?, ?, ?)
                """,
                (
                    None,
                    str(fault.error_id),
                    str(fault.error_message),
                    str(fault.station),
                    int(fault.line_id),
                    int(fault.product_number),
                    occurrence_time.isoformat(timespec="milliseconds"),
                    json.dumps(
                        measurements,
                        ensure_ascii=False,
                        default=_json_default,
                    ),
                    getattr(fault, "sample_time_s", None),
                    DATA_SCHEMA_VERSION,
                ),
            )
            numeric_id = int(cursor.lastrowid)
            incident_id = f"INC-{numeric_id:06d}"
            snapshot_relative_path = Path("incident_snapshots") / f"{incident_id}.json"

            snapshot = {
                "schema_version": DATA_SCHEMA_VERSION,
                "incident_id": incident_id,
                "occurrence_time": occurrence_time.isoformat(timespec="milliseconds"),
                "fault": {
                    "error_id": str(fault.error_id),
                    "error_message": str(fault.error_message),
                    "station": str(fault.station),
                    "line_id": int(fault.line_id),
                    "product_number": int(fault.product_number),
                    "fault_sample_time_s": getattr(fault, "sample_time_s", None),
                    "measurements": measurements,
                },
                "history_record_count": len(history),
                "production_history": history,
            }
            snapshot_path = self.data_dir / snapshot_relative_path
            snapshot_path.write_text(
                json.dumps(
                    snapshot,
                    ensure_ascii=False,
                    default=_json_default,
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )

            connection.execute(
                """
                UPDATE incidents
                SET incident_id = ?, snapshot_path = ?
                WHERE id = ?
                """,
                (
                    incident_id,
                    snapshot_relative_path.as_posix(),
                    numeric_id,
                ),
            )

        return incident_id

    def repair_incident(
        self,
        incident_id: str,
        repair_time: datetime,
        repair_comment: str,
    ) -> bool:
        """Close one OPEN incident with simulated repair time and operator text."""
        with self._io_lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT occurrence_time
                FROM incidents
                WHERE incident_id = ? AND status = 'OPEN'
                """,
                (incident_id,),
            ).fetchone()
            if row is None:
                return False

            occurrence_time = datetime.fromisoformat(str(row["occurrence_time"]))
            downtime_seconds = max(
                0.0,
                (repair_time - occurrence_time).total_seconds(),
            )
            connection.execute(
                """
                UPDATE incidents
                SET status = 'REPAIRED',
                    repair_time = ?,
                    downtime_seconds = ?,
                    repair_comment = ?
                WHERE incident_id = ?
                """,
                (
                    repair_time.isoformat(timespec="milliseconds"),
                    downtime_seconds,
                    repair_comment,
                    incident_id,
                ),
            )
        return True

    def repair_all_open_incidents(
        self,
        repair_time: datetime,
        repair_comment: str = "Simulation restarted / line reset",
    ) -> list[str]:
        """Implicitly repair incidents left OPEN by a previous app session."""
        repaired_ids: list[str] = []
        with self._io_lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT incident_id, occurrence_time
                FROM incidents
                WHERE status = 'OPEN'
                ORDER BY id
                """
            ).fetchall()

            for row in rows:
                occurrence_time = datetime.fromisoformat(str(row["occurrence_time"]))
                downtime_seconds = max(
                    0.0,
                    (repair_time - occurrence_time).total_seconds(),
                )
                incident_id = str(row["incident_id"])
                connection.execute(
                    """
                    UPDATE incidents
                    SET status = 'REPAIRED',
                        repair_time = ?,
                        downtime_seconds = ?,
                        repair_comment = ?
                    WHERE incident_id = ?
                    """,
                    (
                        repair_time.isoformat(timespec="milliseconds"),
                        downtime_seconds,
                        repair_comment,
                        incident_id,
                    ),
                )
                repaired_ids.append(incident_id)

        return repaired_ids

    def list_incidents(self) -> list[dict[str, Any]]:
        """Return incident rows as plain dictionaries for deterministic tests/tools."""
        self.initialize()
        with self._io_lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM incidents ORDER BY id"
            ).fetchall()
        return [dict(row) for row in rows]

    def backup_and_reset(self) -> Path:
        """Backup active history, then initialize an empty active data set."""
        self.initialize()
        with self._io_lock:
            backup_dir = self._next_backup_directory()
            backup_dir.mkdir(parents=True, exist_ok=False)

            for source in (self.db_path, self.runtime_state_path):
                if source.exists():
                    shutil.copy2(source, backup_dir / source.name)

            if self.logs_dir.exists():
                shutil.copytree(self.logs_dir, backup_dir / "logs")
            if self.snapshots_dir.exists():
                shutil.copytree(
                    self.snapshots_dir,
                    backup_dir / "incident_snapshots",
                )

            if self.db_path.exists():
                self.db_path.unlink()
            if self.runtime_state_path.exists():
                self.runtime_state_path.unlink()
            shutil.rmtree(self.logs_dir, ignore_errors=True)
            shutil.rmtree(self.snapshots_dir, ignore_errors=True)

            self.logs_dir.mkdir(parents=True, exist_ok=True)
            self.snapshots_dir.mkdir(parents=True, exist_ok=True)
            self._initialize_database()
            self._write_runtime_state(
                {
                    "schema_version": DATA_SCHEMA_VERSION,
                    "last_simulated_time": None,
                    "product_numbers": DEFAULT_PRODUCT_NUMBERS.copy(),
                }
            )

        return backup_dir

    def _next_backup_directory(self) -> Path:
        base_name = f"backup_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}"
        candidate = self.backups_dir / base_name
        suffix = 1
        while candidate.exists():
            candidate = self.backups_dir / f"{base_name}_{suffix:02d}"
            suffix += 1
        return candidate


def _json_default(value: Any) -> Any:
    """Convert common scalar types used by pandas/numpy snapshots."""
    if isinstance(value, datetime):
        return value.isoformat(timespec="milliseconds")
    item = getattr(value, "item", None)
    if callable(item):
        return item()
    return str(value)
