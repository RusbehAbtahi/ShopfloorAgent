"""Main MES runtime for ShopfloorAgent.

Responsibilities kept here:
- four-line simulation orchestration;
- one global simulated plant clock;
- event-to-persistence coordination.

Concrete fault knowledge stays in fault_detection.py.
Generic line-stop action stays in alarm_manager.py.
Persistent operational data stays in mes_data_store.py.
Streamlit presentation stays in mes_gui.py.
"""

from __future__ import annotations

import atexit
from datetime import datetime, timedelta
from pathlib import Path
import threading
import time
from typing import Any

import pandas as pd
import streamlit as st

from alarm_manager import raise_alarm
from fault_detection import FaultEvent, check_cycle_completion, evaluate_sample
from mes_data_store import MESDataStore
from mes_gui import (
    configure_page,
    render_fault_controls,
    render_start_controls,
    render_status,
    show_start_result,
)
from simulation_helpers import LineState, load_reference_data, prepare_next_product


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
NORMAL_CSV_PATH = BASE_DIR / "normal_cycle_90s.csv"

FAULT_CSV_PATHS = {
    "stuck_screw": BASE_DIR / "fault_screw_early_torque.csv",
    "station1_alignment": BASE_DIR / "fault_station1_alignment.csv",
    "no_screw_engagement": BASE_DIR / "fault_screw_no_engagement.csv",
    "station2_no_exit": BASE_DIR / "fault_station2_no_exit.csv",
    "station3_final_inspection": BASE_DIR / "fault_station3_final_inspection.csv",
}

NUMBER_OF_LINES = 4
SIMULATED_SAMPLE_SECONDS = 0.1
REAL_PAUSE_BETWEEN_PRODUCTS_S = 1.0
SCHEDULER_SLEEP_S = 0.0005
RUNTIME_PERSIST_INTERVAL_SIMULATED_S = 10.0


class SimulationController:
    """Own line states, the global plant clock, and persistence coordination."""

    def __init__(
        self,
        normal_data: pd.DataFrame,
        fault_data: dict[str, pd.DataFrame],
        start_datetime: datetime,
        data_store: MESDataStore,
        initial_product_numbers: dict[int, int] | None = None,
    ) -> None:
        self.normal_data = normal_data
        self.fault_data = fault_data
        self.data_store = data_store
        self.simulated_time = start_datetime

        initial_product_numbers = initial_product_numbers or {}
        self.lines = {
            line_id: LineState(
                line_id=line_id,
                product_number=int(initial_product_numbers.get(line_id, 1)),
            )
            for line_id in range(1, NUMBER_OF_LINES + 1)
        }

        self.line_data = {
            line_id: self.normal_data for line_id in range(1, NUMBER_OF_LINES + 1)
        }
        self.line_cycle_names = {
            line_id: NORMAL_CSV_PATH.name
            for line_id in range(1, NUMBER_OF_LINES + 1)
        }

        # Complete variable history for this running MES session. At a fault it
        # is copied into the incident snapshot as evidence from session start to
        # the exact fault sample.
        self.history_buffer: list[dict[str, Any]] = []

        self.simulation_running = False
        self.lock = threading.Lock()
        self.worker_thread: threading.Thread | None = None
        self._simulated_seconds_since_persist = 0.0
        self._persistence_active = True
        atexit.register(self._persist_on_exit)

    def start(self) -> None:
        """Start one background worker for all four production lines."""
        with self.lock:
            if self.simulation_running:
                return
            self.simulation_running = True
            self._persist_runtime_state_locked()

        self.worker_thread = threading.Thread(
            target=self._run_loop,
            name="shopfloor-mes-simulation",
            daemon=True,
        )
        self.worker_thread.start()

    def stop(self) -> None:
        """Stop this controller and persist its exact continuity point."""
        with self.lock:
            if self._persistence_active:
                self._persist_runtime_state_locked()
            self.simulation_running = False
            self._persistence_active = False

        thread = self.worker_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)

    def _persist_on_exit(self) -> None:
        """Best-effort exact save on normal Python/Streamlit process shutdown."""
        try:
            with self.lock:
                if self._persistence_active:
                    self._persist_runtime_state_locked()
                    self._persistence_active = False
        except Exception:
            # Shutdown persistence is a last safeguard; normal event persistence
            # already keeps runtime_state.json current during operation.
            pass

    def _product_numbers_locked(self) -> dict[int, int]:
        return {
            line_id: line.product_number
            for line_id, line in self.lines.items()
        }

    def _persist_runtime_state_locked(self) -> None:
        self.data_store.save_runtime_state(
            simulated_time=self.simulated_time,
            product_numbers=self._product_numbers_locked(),
        )
        self._simulated_seconds_since_persist = 0.0

    def can_inject_fault(self, line_id: int) -> bool:
        with self.lock:
            line = self.lines[line_id]
            return (
                self.simulation_running
                and line.running
                and not line.fault_active
                and self.line_cycle_names[line_id] == NORMAL_CSV_PATH.name
            )

    def can_repair_line(self, line_id: int) -> bool:
        with self.lock:
            line = self.lines[line_id]
            return self.simulation_running and (line.fault_active or not line.running)

    def repair_line(self, line_id: int, repair_comment: str = "") -> bool:
        """Repair one stopped line at the current global simulated time."""
        with self.lock:
            line = self.lines[line_id]
            if not self.simulation_running or (line.running and not line.fault_active):
                return False

            incident_id = line.active_incident_id
            if incident_id:
                self.data_store.repair_incident(
                    incident_id=incident_id,
                    repair_time=self.simulated_time,
                    repair_comment=repair_comment.strip(),
                )

            self.line_data[line_id] = self.normal_data
            self.line_cycle_names[line_id] = NORMAL_CSV_PATH.name

            line.running = True
            line.fault_active = False
            line.fault_id = ""
            line.fault_message = ""
            line.fault_station = ""
            line.active_incident_id = ""
            line.sample_index = 0
            line.b_screwed = False
            line.next_real_start_monotonic = 0.0

            self._persist_runtime_state_locked()

            print(
                f"REPAIR - Line {line_id} | simulated time: {self.simulated_time} | "
                f"{NORMAL_CSV_PATH.name} restored, sample index reset to 0"
            )

        return True

    def inject_fault(self, line_id: int, fault_key: str) -> bool:
        """Load one deterministic fault cycle into only the selected line."""
        with self.lock:
            line = self.lines[line_id]
            if (
                not self.simulation_running
                or not line.running
                or line.fault_active
                or self.line_cycle_names[line_id] != NORMAL_CSV_PATH.name
            ):
                return False

            selected_fault_data = self.fault_data[fault_key]
            selected_fault_name = FAULT_CSV_PATHS[fault_key].name
            self.line_data[line_id] = selected_fault_data
            self.line_cycle_names[line_id] = selected_fault_name

            # The test fault replaces the current cycle from its beginning, but
            # it remains the same product, so its START event is not duplicated.
            line.sample_index = 0
            line.b_screwed = False
            line.next_real_start_monotonic = 0.0

            print(
                f"FAULT INJECTION - Line {line_id}: "
                f"{selected_fault_name} loaded"
            )

        return True

    def _run_loop(self) -> None:
        """Main scheduler: active lines share one global simulation tick."""
        while True:
            with self.lock:
                if not self.simulation_running:
                    return
                line_ids = list(self.lines.keys())

            processed_any_sample = False
            for line_id in line_ids:
                if self._process_one_sample(line_id):
                    processed_any_sample = True

            if processed_any_sample:
                with self.lock:
                    self.simulated_time += timedelta(
                        seconds=SIMULATED_SAMPLE_SECONDS
                    )
                    self._simulated_seconds_since_persist += SIMULATED_SAMPLE_SECONDS
                    if (
                        self._simulated_seconds_since_persist
                        >= RUNTIME_PERSIST_INTERVAL_SIMULATED_S
                    ):
                        self._persist_runtime_state_locked()

            time.sleep(SCHEDULER_SLEEP_S)

    def _process_one_sample(self, line_id: int) -> bool:
        """Process one line sample; return whether one sample was evaluated."""
        with self.lock:
            line = self.lines[line_id]
            if not line.running or line.fault_active:
                return False
            if time.monotonic() < line.next_real_start_monotonic:
                return False

            if line.sample_index == 0 and not line.product_start_logged:
                line.product_start_logged = True
                self.data_store.append_product_event(
                    event="START",
                    line_id=line.line_id,
                    product_number=line.product_number,
                    simulated_time=self.simulated_time,
                )
                print(
                    f"Product {line.product_number} START - Line {line.line_id} "
                    f"| simulated time: {self.simulated_time}"
                )

            data = self.line_data[line_id]
            row = data.iloc[line.sample_index]
            self._append_history_record_locked(line, row)

            evaluation = evaluate_sample(
                row=row,
                line_id=line.line_id,
                product_number=line.product_number,
                already_screwed=line.b_screwed,
            )

            if evaluation.fault is not None:
                raise_alarm(line, evaluation.fault)
                self._record_incident_locked(line, evaluation.fault)
                return True

            if evaluation.screwing_successful:
                line.b_screwed = True

            line.sample_index += 1
            if line.sample_index >= len(data):
                self._finish_product_locked(line)

            return True

    def _append_history_record_locked(
        self,
        line: LineState,
        row: pd.Series,
    ) -> None:
        variables = {
            str(name): _plain_scalar(value)
            for name, value in row.to_dict().items()
        }
        self.history_buffer.append(
            {
                "simulated_time": self.simulated_time.isoformat(
                    timespec="milliseconds"
                ),
                "line_id": line.line_id,
                "product_number": line.product_number,
                "sample_index": line.sample_index,
                "cycle": self.line_cycle_names[line.line_id],
                "variables": variables,
            }
        )

    def _record_incident_locked(
        self,
        line: LineState,
        fault: FaultEvent,
    ) -> None:
        incident_id = self.data_store.create_incident(
            fault=fault,
            occurrence_time=self.simulated_time,
            history=list(self.history_buffer),
        )
        line.active_incident_id = incident_id
        self._persist_runtime_state_locked()
        print(
            f"INCIDENT {incident_id} saved | simulated time: "
            f"{self.simulated_time}"
        )

    def _finish_product_locked(self, line: LineState) -> None:
        completion_fault = check_cycle_completion(
            line_id=line.line_id,
            product_number=line.product_number,
            b_screwed=line.b_screwed,
        )
        if completion_fault is not None:
            raise_alarm(line, completion_fault)
            self._record_incident_locked(line, completion_fault)
            return

        self.data_store.append_product_event(
            event="FINISHED",
            line_id=line.line_id,
            product_number=line.product_number,
            simulated_time=self.simulated_time,
        )
        print(
            f"Product {line.product_number} FINISHED - Line {line.line_id} "
            f"| simulated time: {self.simulated_time}"
        )

        prepare_next_product(
            line=line,
            real_pause_seconds=REAL_PAUSE_BETWEEN_PRODUCTS_S,
        )
        self._persist_runtime_state_locked()


def _plain_scalar(value: Any) -> Any:
    """Convert pandas/numpy scalar values into JSON-safe Python values."""
    if pd.isna(value):
        return None
    item = getattr(value, "item", None)
    if callable(item):
        return item()
    return value


def main() -> None:
    """Connect GUI, continuous history state, and the simulation controller."""
    configure_page()

    data_store = MESDataStore(DATA_DIR)
    data_store.initialize()

    reset_message = st.session_state.pop("history_reset_backup", None)
    if reset_message:
        st.success(f"History reset. Backup created: {reset_message}")

    controller: SimulationController | None = st.session_state.get(
        "simulation_controller"
    )
    resume_time = data_store.get_resume_time()

    start_datetime, start_requested, reset_requested = render_start_controls(
        resume_time=resume_time,
        simulation_running=bool(controller and controller.simulation_running),
    )

    if reset_requested:
        if controller is not None:
            controller.stop()
        backup_dir = data_store.backup_and_reset()
        st.session_state.pop("simulation_controller", None)
        st.session_state.pop("repair_comment", None)
        st.session_state["history_reset_backup"] = str(
            backup_dir.relative_to(DATA_DIR)
        )
        st.rerun()

    if start_requested:
        if controller is None or not controller.simulation_running:
            # First-ever start uses the GUI. Every later start continues from
            # the persisted plant time and ignores arbitrary GUI time changes.
            actual_start_time = resume_time or start_datetime

            if resume_time is not None:
                repaired_ids = data_store.repair_all_open_incidents(
                    repair_time=actual_start_time,
                    repair_comment="Simulation restarted / line reset",
                )
                for incident_id in repaired_ids:
                    print(
                        f"IMPLICIT REPAIR - {incident_id} | simulated time: "
                        f"{actual_start_time} | Simulation restarted / line reset"
                    )

            controller = SimulationController(
                normal_data=load_reference_data(NORMAL_CSV_PATH),
                fault_data={
                    fault_key: load_reference_data(csv_path)
                    for fault_key, csv_path in FAULT_CSV_PATHS.items()
                },
                start_datetime=actual_start_time,
                data_store=data_store,
                initial_product_numbers=data_store.get_product_numbers(),
            )
            st.session_state["simulation_controller"] = controller
            controller.start()
            show_start_result(started=True)
        else:
            show_start_result(started=False)

    render_fault_controls()
    render_status()


if __name__ == "__main__":
    main()
