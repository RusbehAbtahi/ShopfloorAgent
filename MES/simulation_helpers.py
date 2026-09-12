"""Neutral simulation helpers for the Shopfloor MES.

This module contains only generic simulation state and utility functions.
It deliberately knows nothing about a particular station, fault, torque rule,
or error ID. Those concrete production rules belong in fault_detection.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time as datetime_time, timedelta
from pathlib import Path
import time

import pandas as pd


@dataclass
class LineState:
    """Mutable runtime state for one production line.

    The fields are intentionally generic. The simulation controller and GUI
    can use the same object, while fault-specific knowledge remains outside
    this module.
    """

    line_id: int
    running: bool = True
    sample_index: int = 0
    product_number: int = 1
    b_screwed: bool = False

    # Generic fault state. Concrete meanings/criteria live in fault_detection.
    fault_active: bool = False
    fault_id: str = ""
    fault_message: str = ""
    fault_station: str = ""

    # Independent simulated time for this line.
    simulated_cycle_start: datetime | None = None

    # Real-time throttle between products. This does not affect simulated time.
    next_real_start_monotonic: float = 0.0


def load_reference_data(csv_path: Path, expected_rows: int = 900) -> pd.DataFrame:
    """Load and minimally validate a reference production CSV."""
    if not csv_path.exists():
        raise FileNotFoundError(f"Reference CSV not found: {csv_path}")

    data = pd.read_csv(csv_path)

    # These are only the generic columns required by the current runtime.
    # More specialized fault detectors may use additional columns later.
    required_columns = {"time_s", "torque_nm", "screw_angle_deg"}
    missing = required_columns.difference(data.columns)
    if missing:
        raise ValueError(f"Reference CSV missing columns: {sorted(missing)}")

    if len(data) != expected_rows:
        raise ValueError(f"Expected {expected_rows} rows, found {len(data)}")

    return data


def build_start_datetime(
    selected_date: date, hour: int, minute: int, second: int
) -> datetime:
    """Build an exact datetime from date plus hour/minute/second values."""
    selected_time = datetime_time(hour=hour, minute=minute, second=second)
    return datetime.combine(selected_date, selected_time)


def prepare_next_product(
    line: LineState,
    simulated_cycle_seconds: int,
    real_pause_seconds: float,
) -> None:
    """Reset generic per-product state and advance this line's simulated time."""
    line.sample_index = 0
    line.product_number += 1
    line.b_screwed = False

    if line.simulated_cycle_start is not None:
        line.simulated_cycle_start += timedelta(seconds=simulated_cycle_seconds)

    line.next_real_start_monotonic = time.monotonic() + real_pause_seconds
