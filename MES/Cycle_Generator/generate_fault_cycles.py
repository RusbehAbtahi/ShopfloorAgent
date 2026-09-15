"""Generate deterministic faulty production cycles from the golden normal cycle.

The golden 90-second CSV remains the source of truth. Each function copies the
normal cycle and changes only the signals needed for one specific fault. This
keeps every scenario deterministic, easy to explain, and easy to compare with
the normal production cycle.
"""

from pathlib import Path

import pandas as pd


GENERATOR_DIR = Path(__file__).resolve().parent
MES_DIR = GENERATOR_DIR.parent
NORMAL_CYCLE_CSV = MES_DIR / "normal_cycle_90s.csv"

FAULT_SCREW_EARLY_TORQUE_CSV = MES_DIR / "fault_screw_early_torque.csv"
FAULT_ST1_ALIGNMENT_CSV = MES_DIR / "fault_station1_alignment.csv"
FAULT_SCREW_NO_ENGAGEMENT_CSV = MES_DIR / "fault_screw_no_engagement.csv"
FAULT_ST2_NO_EXIT_CSV = MES_DIR / "fault_station2_no_exit.csv"
FAULT_ST3_FINAL_INSPECTION_CSV = MES_DIR / "fault_station3_final_inspection.csv"

TARGET_TORQUE_NM = 12.0

# Fault 1: screw becomes mechanically stuck after 900 degrees of rotation.
# The angle then remains at 900 degrees while torque rises to the target.
# Starting the fault exactly when the golden cycle reaches 900 degrees keeps
# accumulated rotation physically monotonic (it never jumps backwards).
EARLY_TORQUE_FAULT_START_S = 35.5
EARLY_TORQUE_FAULT_ANGLE_DEG = 900.0

# Fault 2: Station 1 alignment is not confirmed at the 11.5 s checkpoint.
ST1_ALIGNMENT_CHECK_S = 11.5

# Fault 3: screwdriver rotates freely but never develops fastening torque.
# The normal cycle already provides the rotation profile; only screw presence
# and torque are changed during the fastening interval.
SCREW_FASTENING_START_S = 35.0
SCREW_FASTENING_END_S = 39.5

# Fault 4: Station 2 exit event is expected at 60.0 s but never occurs.
ST2_EXIT_START_S = 60.0
ST2_EXIT_END_S = 62.0

# Fault 5: one final inspection sensor stays NOK during its normal active window.
ST3_FINAL_CHECK_START_S = 71.3
ST3_FINAL_CHECK_END_S = 79.5
ST3_FAILED_SENSOR = "st3_s4_check"


def _load_normal_cycle() -> pd.DataFrame:
    """Load the golden cycle and validate all columns used by fault generators."""
    if not NORMAL_CYCLE_CSV.exists():
        raise FileNotFoundError(f"Normal cycle not found: {NORMAL_CYCLE_CSV}")

    data = pd.read_csv(NORMAL_CYCLE_CSV)

    required_columns = {
        "time_s",
        "torque_nm",
        "screw_angle_deg",
        "st1_s1_part_a_seated",
        "st1_s2_part_b_seated",
        "st1_s3_alignment_ok",
        "st2_s1_screw_loaded",
        "st2_s2_assembly_exit",
        "st3_s1_check",
        "st3_s2_check",
        "st3_s3_check",
        "st3_s4_check",
        "st3_s5_check",
        "st3_s6_check",
    }
    missing = required_columns.difference(data.columns)
    if missing:
        raise ValueError(f"Normal cycle missing columns: {sorted(missing)}")

    if len(data) != 900:
        raise ValueError(f"Expected 900 rows, found {len(data)}")

    return data


def _generate_screw_early_torque(normal_cycle: pd.DataFrame) -> pd.DataFrame:
    """Fault 1: screw is stuck and reaches maximum torque far too early."""
    fault_cycle = normal_cycle.copy(deep=True)
    fault_window = fault_cycle["time_s"] >= EARLY_TORQUE_FAULT_START_S

    fault_cycle.loc[fault_window, "screw_angle_deg"] = EARLY_TORQUE_FAULT_ANGLE_DEG
    fault_cycle.loc[fault_window, "torque_nm"] = TARGET_TORQUE_NM

    return fault_cycle


def _generate_station1_alignment_failure(normal_cycle: pd.DataFrame) -> pd.DataFrame:
    """Fault 2: final Station 1 alignment sensor never confirms alignment.

    Part A and Part B remain correctly seated; only the final alignment signal
    is forced low. At 11.5 s the detector therefore sees a realistic single
    positioning/alignment failure rather than several unrelated sensor faults.
    """
    fault_cycle = normal_cycle.copy(deep=True)

    normal_alignment_window = (
        (fault_cycle["time_s"] >= ST1_ALIGNMENT_CHECK_S)
        & (fault_cycle["time_s"] < 19.0)
    )
    fault_cycle.loc[normal_alignment_window, "st1_s3_alignment_ok"] = 0

    return fault_cycle


def _generate_screw_no_engagement(normal_cycle: pd.DataFrame) -> pd.DataFrame:
    """Fault 3: screwdriver rotates freely but the screw does not engage.

    The angle profile remains the normal rotating profile, representing a tool
    that is spinning. The screw-loaded signal is low and torque remains zero,
    so no meaningful mechanical engagement is produced.
    """
    fault_cycle = normal_cycle.copy(deep=True)

    fastening_window = (
        (fault_cycle["time_s"] >= SCREW_FASTENING_START_S)
        & (fault_cycle["time_s"] < SCREW_FASTENING_END_S)
    )
    fault_cycle.loc[fastening_window, "st2_s1_screw_loaded"] = 0
    fault_cycle.loc[fastening_window, "torque_nm"] = 0.0

    return fault_cycle


def _generate_station2_no_exit(normal_cycle: pd.DataFrame) -> pd.DataFrame:
    """Fault 4: fastening succeeds, but the assembly never triggers the exit sensor."""
    fault_cycle = normal_cycle.copy(deep=True)

    exit_window = (
        (fault_cycle["time_s"] >= ST2_EXIT_START_S)
        & (fault_cycle["time_s"] < ST2_EXIT_END_S)
    )
    fault_cycle.loc[exit_window, "st2_s2_assembly_exit"] = 0

    return fault_cycle


def _generate_station3_final_inspection_failure(
    normal_cycle: pd.DataFrame,
) -> pd.DataFrame:
    """Fault 5: one Station 3 final inspection sensor remains NOK."""
    fault_cycle = normal_cycle.copy(deep=True)

    inspection_window = (
        (fault_cycle["time_s"] >= ST3_FINAL_CHECK_START_S)
        & (fault_cycle["time_s"] < ST3_FINAL_CHECK_END_S)
    )
    fault_cycle.loc[inspection_window, ST3_FAILED_SENSOR] = 0

    return fault_cycle


def _save_fault(data: pd.DataFrame, output_path: Path, description: str) -> None:
    """Save one 900-row deterministic fault cycle and print a concise summary."""
    if len(data) != 900:
        raise ValueError(f"Expected 900 rows for {output_path.name}, found {len(data)}")

    data.to_csv(output_path, index=False)
    print(f"Generated: {output_path.name} - {description}")


def main() -> None:
    """Generate all five currently demonstrated production-fault CSV files."""
    normal_cycle = _load_normal_cycle()
    print(f"Loaded golden cycle: {NORMAL_CYCLE_CSV.name}")

    _save_fault(
        _generate_screw_early_torque(normal_cycle),
        FAULT_SCREW_EARLY_TORQUE_CSV,
        "stuck screw / early target torque",
    )
    _save_fault(
        _generate_station1_alignment_failure(normal_cycle),
        FAULT_ST1_ALIGNMENT_CSV,
        "Station 1 alignment sensor not confirmed",
    )
    _save_fault(
        _generate_screw_no_engagement(normal_cycle),
        FAULT_SCREW_NO_ENGAGEMENT_CSV,
        "free rotation / no screw engagement",
    )
    _save_fault(
        _generate_station2_no_exit(normal_cycle),
        FAULT_ST2_NO_EXIT_CSV,
        "Station 2 exit sensor missing",
    )
    _save_fault(
        _generate_station3_final_inspection_failure(normal_cycle),
        FAULT_ST3_FINAL_INSPECTION_CSV,
        "Station 3 final inspection NOK",
    )


if __name__ == "__main__":
    main()
