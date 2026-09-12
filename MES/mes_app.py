"""Main MES runtime for ShopfloorAgent.

This file intentionally contains only:
- fixed runtime configuration;
- the four-line simulation controller and its loop;
- main application orchestration.

Concrete production-fault knowledge is in fault_detection.py.
Generic alarm action is in alarm_manager.py.
Neutral state/utilities are in simulation_helpers.py.
Streamlit presentation is in mes_gui.py.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import threading
import time

import pandas as pd
import streamlit as st

from alarm_manager import raise_alarm
from fault_detection import check_cycle_completion, evaluate_sample
from mes_gui import (
    configure_page,
    render_fault_controls,
    render_start_controls,
    render_status,
    show_fault_injection_result,
    show_start_result,
)
from simulation_helpers import LineState, load_reference_data, prepare_next_product


# ---------------------------------------------------------------------------
# Runtime configuration
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
NORMAL_CSV_PATH = BASE_DIR / "normal_cycle_90s.csv"

# The GUI uses these stable keys. Each key points to one deterministic fault
# cycle generated from the golden normal cycle.
FAULT_CSV_PATHS = {
    "stuck_screw": BASE_DIR / "fault_screw_early_torque.csv",
    "station1_alignment": BASE_DIR / "fault_station1_alignment.csv",
    "no_screw_engagement": BASE_DIR / "fault_screw_no_engagement.csv",
    "station2_no_exit": BASE_DIR / "fault_station2_no_exit.csv",
    "station3_final_inspection": BASE_DIR / "fault_station3_final_inspection.csv",
}

NUMBER_OF_LINES = 4
SIMULATED_CYCLE_SECONDS = 90
REAL_PAUSE_BETWEEN_PRODUCTS_S = 1.0
SCHEDULER_SLEEP_S = 0.0005


# ---------------------------------------------------------------------------
# Four-line simulation controller
# ---------------------------------------------------------------------------

class SimulationController:
    """Own the line states and run the common production loop."""

    def __init__(
        self,
        normal_data: pd.DataFrame,
        fault_data: dict[str, pd.DataFrame],
        start_datetime: datetime,
    ) -> None:
        # Load each dataset once. Production lines only switch references to
        # these already loaded DataFrames; no CSV is read inside the worker.
        self.normal_data = normal_data
        self.fault_data = fault_data

        self.lines = {
            line_id: LineState(
                line_id=line_id,
                simulated_cycle_start=start_datetime,
            )
            for line_id in range(1, NUMBER_OF_LINES + 1)
        }

        # Every line starts on the golden cycle. Because the references are
        # independent, a GUI action can replace one line without affecting the
        # sample index or dataset of any other line.
        self.line_data = {
            line_id: self.normal_data for line_id in range(1, NUMBER_OF_LINES + 1)
        }
        self.line_cycle_names = {
            line_id: NORMAL_CSV_PATH.name
            for line_id in range(1, NUMBER_OF_LINES + 1)
        }

        self.simulation_running = False

        # Streamlit/UI and the worker thread share this controller. The lock
        # makes line-state and dataset changes atomic relative to the loop.
        self.lock = threading.Lock()
        self.worker_thread: threading.Thread | None = None

    def start(self) -> None:
        """Start one background worker for all four production lines."""
        with self.lock:
            if self.simulation_running:
                return
            self.simulation_running = True

        self.worker_thread = threading.Thread(
            target=self._run_loop,
            name="shopfloor-mes-simulation",
            daemon=True,
        )
        self.worker_thread.start()

    def can_inject_fault(self, line_id: int) -> bool:
        """Return whether one line can currently accept a new fault cycle."""
        with self.lock:
            line = self.lines[line_id]
            return (
                self.simulation_running
                and line.running
                and not line.fault_active
                and self.line_cycle_names[line_id] == NORMAL_CSV_PATH.name
            )

    def inject_fault(self, line_id: int, fault_key: str) -> bool:
        """Load one selected deterministic fault cycle into one line.

        Only the selected line restarts at sample 0. The other three lines keep
        their current indices and continue independently.
        """
        with self.lock:
            line = self.lines[line_id]

            # Reject both an already-stopped line AND a line that already has a
            # fault cycle pending but has not reached its detector checkpoint yet.
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

            # Restart only this line's current cycle from its first sample.
            line.sample_index = 0
            line.b_screwed = False
            line.next_real_start_monotonic = 0.0

            print(
                f"FAULT INJECTION - Line {line_id}: "
                f"{selected_fault_name} loaded"
            )

        return True

    def _run_loop(self) -> None:
        """Main scheduler loop: each active line gets one sample per pass."""
        while True:
            with self.lock:
                if not self.simulation_running:
                    return
                line_ids = list(self.lines.keys())

            for line_id in line_ids:
                self._process_one_sample(line_id)

            # Wall-clock throttle only; simulated time comes from the CSV.
            time.sleep(SCHEDULER_SLEEP_S)

    def _process_one_sample(self, line_id: int) -> None:
        """Process exactly one CSV sample for one production line."""
        with self.lock:
            line = self.lines[line_id]

            # Faulted/stopped lines remain frozen. The common scheduler still
            # visits them, but they return immediately and consume no samples.
            if not line.running or line.fault_active:
                return

            if time.monotonic() < line.next_real_start_monotonic:
                return

            if line.sample_index == 0:
                print(
                    f"Product {line.product_number} - Line {line.line_id} "
                    f"| simulated start: {line.simulated_cycle_start}"
                )

            # Each line reads from its own currently selected cycle.
            data = self.line_data[line_id]
            row = data.iloc[line.sample_index]

            # fault_detection.py performs all five concrete production checks.
            # The MES runtime receives only a standardized result.
            evaluation = evaluate_sample(
                row=row,
                line_id=line.line_id,
                product_number=line.product_number,
                already_screwed=line.b_screwed,
            )

            # Print deterministic acceptance checkpoints when they occur.
            for message in evaluation.acceptance_messages:
                print(
                    f"ACCEPTED - Line {line.line_id}, "
                    f"Product {line.product_number}: {message}"
                )

            # A recognized fault is passed to the generic alarm manager.
            if evaluation.fault is not None:
                raise_alarm(line, evaluation.fault)
                return

            if evaluation.screwing_successful:
                line.b_screwed = True

            # No fault: consume this sample.
            line.sample_index += 1

            if line.sample_index >= len(data):
                self._finish_product(line)

    def _finish_product(self, line: LineState) -> None:
        """Validate cycle completion, then prepare the next product."""
        completion_fault = check_cycle_completion(
            line_id=line.line_id,
            product_number=line.product_number,
            b_screwed=line.b_screwed,
        )

        if completion_fault is not None:
            raise_alarm(line, completion_fault)
            return

        prepare_next_product(
            line=line,
            simulated_cycle_seconds=SIMULATED_CYCLE_SECONDS,
            real_pause_seconds=REAL_PAUSE_BETWEEN_PRODUCTS_S,
        )


# ---------------------------------------------------------------------------
# Main application entry
# ---------------------------------------------------------------------------

def main() -> None:
    """Connect the GUI to the simulation controller."""
    configure_page()

    start_datetime, start_requested = render_start_controls()
    controller: SimulationController | None = st.session_state.get(
        "simulation_controller"
    )

    if start_requested:
        if controller is None or not controller.simulation_running:
            controller = SimulationController(
                normal_data=load_reference_data(NORMAL_CSV_PATH),
                fault_data={
                    fault_key: load_reference_data(csv_path)
                    for fault_key, csv_path in FAULT_CSV_PATHS.items()
                },
                start_datetime=start_datetime,
            )
            st.session_state["simulation_controller"] = controller
            controller.start()
            show_start_result(started=True)
        else:
            show_start_result(started=False)

    # Fault controls appear only after a simulation controller exists.
    controller = st.session_state.get("simulation_controller")
    selected_line, fault_key, fault_label = render_fault_controls(controller)

    if (
        fault_key is not None
        and controller is not None
        and selected_line is not None
    ):
        injected = controller.inject_fault(selected_line, fault_key)
        show_fault_injection_result(
            line_id=selected_line,
            fault_label=fault_label,
            injected=injected,
        )

    render_status()


if __name__ == "__main__":
    main()
