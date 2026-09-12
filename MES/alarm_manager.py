"""Generic alarm handling for the Shopfloor MES.

This module is intentionally neutral to fault type, station, and detection
criteria. It accepts a standardized FaultEvent and applies the common action.
Later SQLite persistence, snapshots, WebSocket notification, or escalation can
be added here without changing the concrete detector functions.
"""

from __future__ import annotations

from fault_detection import FaultEvent
from simulation_helpers import LineState


def raise_alarm(line: LineState, fault: FaultEvent) -> None:
    """Stop one line and copy standardized alarm data into its shared state."""
    line.running = False
    line.fault_active = True
    line.fault_id = fault.error_id
    line.fault_message = fault.error_message
    line.fault_station = fault.station

    # Current implementation only reports to the CLI.
    # Future persistence/escalation belongs here, not in the detectors.
    measurement_text = ""
    if fault.measurements:
        measurement_text = " | " + ", ".join(
            f"{name}={value:.1f}" for name, value in fault.measurements.items()
        )

    print(
        f"ALERT [{fault.error_id}] - Line {fault.line_id}, "
        f"Product {fault.product_number}, {fault.station}: "
        f"{fault.error_message}{measurement_text}"
    )
