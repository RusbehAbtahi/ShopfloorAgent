"""Concrete production-fault recognition for the Shopfloor MES.

This module contains the concrete knowledge of what a production fault means.
The rest of the MES receives only standardized results and therefore does not
need to know which station, sensor, torque rule, or inspection rule failed.

Current demonstrated checks:
1. Station 1 positioning/alignment.
2. Stuck screw / target torque reached too early.
3. No screw / free rotation / invalid screw engagement.
4. Product stuck at Station 2 / expected exit missing.
5. Station 3 final inspection.

The functions are intentionally simple and deterministic because the MES is a
controlled diagnostic simulation, not a high-fidelity physical model.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


# ---------------------------------------------------------------------------
# Concrete process knowledge
# ---------------------------------------------------------------------------

# Normal fastening requires 12 complete revolutions before target torque.
REQUIRED_ROTATION_DEG = 4320.0
TARGET_TORQUE_NM = 12.0

# Deterministic checkpoints taken directly from the golden normal cycle.
# At these timestamps the required normal condition must already be present.
ST1_ALIGNMENT_CHECK_S = 11.5
ST2_ENGAGEMENT_CHECK_S = 38.0
ST2_EXIT_CHECK_S = 60.0
ST3_FINAL_CHECK_S = 71.5
CHECKPOINT_TOLERANCE_S = 0.01

# Stable fault IDs. Later these IDs can be used directly as keys in the
# recommendation/remedy database.
ERR_ST1_ALIGNMENT_FAILED = "S1_ALIGNMENT_FAILED"
ERR_EARLY_TARGET_TORQUE = "S2_EARLY_TARGET_TORQUE"
ERR_NO_SCREW_ENGAGEMENT = "S2_NO_SCREW_ENGAGEMENT"
ERR_PRODUCT_STUCK_NO_EXIT = "S2_PRODUCT_STUCK_NO_EXIT"
ERR_FINAL_INSPECTION_FAILED = "S3_FINAL_INSPECTION_FAILED"
ERR_SCREW_NOT_COMPLETED = "S2_SCREW_NOT_COMPLETED"

STATION_POSITIONING = "Station 1"
STATION_FASTENING = "Station 2"
STATION_FINAL_INSPECTION = "Station 3"

# Human-readable acceptance messages. These are deliberately kept beside the
# matching fault logic so all concrete process meaning stays in one module.
OK_ST1_ALIGNMENT = "Station 1 positioning and alignment accepted"
OK_SCREW_FASTENING = "Screw fastening accepted"
OK_SCREW_ENGAGEMENT = "Screw engagement and torque-angle behavior accepted"
OK_ST2_EXIT = "Station 2 product exit accepted"
OK_ST3_FINAL_INSPECTION = "Station 3 final inspection accepted"


# ---------------------------------------------------------------------------
# Standardized detector outputs
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FaultEvent:
    """Standardized fault information returned by every detector."""

    error_id: str
    error_message: str
    station: str
    line_id: int
    product_number: int
    sample_time_s: float | None = None
    measurements: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class CheckResult:
    """Generic result for a deterministic production-condition check."""

    accepted: bool = False
    acceptance_message: str = ""
    fault: FaultEvent | None = None


@dataclass(frozen=True)
class ScrewCheckResult:
    """Result of evaluating the fastening conditions for one sample."""

    screwing_successful: bool = False
    acceptance_message: str = ""
    fault: FaultEvent | None = None


# ---------------------------------------------------------------------------
# Small internal helper
# ---------------------------------------------------------------------------

def _at_checkpoint(sample_time_s: float, checkpoint_s: float) -> bool:
    """Return True only for the one sample representing a defined checkpoint."""
    return abs(sample_time_s - checkpoint_s) <= CHECKPOINT_TOLERANCE_S


# ---------------------------------------------------------------------------
# Check 1: Station 1 positioning/alignment
# ---------------------------------------------------------------------------

def check_station_1_alignment(
    row: pd.Series,
    line_id: int,
    product_number: int,
) -> CheckResult:
    """Check that all required Station 1 positioning sensors are confirmed.

    The golden cycle has all three required positioning/alignment sensors high
    at 11.5 s. We evaluate the condition once at that deterministic checkpoint.
    """
    sample_time_s = float(row["time_s"])
    if not _at_checkpoint(sample_time_s, ST1_ALIGNMENT_CHECK_S):
        return CheckResult()

    sensor_values = {
        "st1_s1_part_a_seated": float(row["st1_s1_part_a_seated"]),
        "st1_s2_part_b_seated": float(row["st1_s2_part_b_seated"]),
        "st1_s3_alignment_ok": float(row["st1_s3_alignment_ok"]),
    }

    if all(value == 1.0 for value in sensor_values.values()):
        return CheckResult(
            accepted=True,
            acceptance_message=OK_ST1_ALIGNMENT,
        )

    return CheckResult(
        fault=FaultEvent(
            error_id=ERR_ST1_ALIGNMENT_FAILED,
            error_message=(
                "Station 1 alignment failed: one or more positioning sensors "
                "are not confirmed"
            ),
            station=STATION_POSITIONING,
            line_id=line_id,
            product_number=product_number,
            sample_time_s=sample_time_s,
            measurements=sensor_values,
        )
    )


# ---------------------------------------------------------------------------
# Check 2: stuck screw / target torque too early
# ---------------------------------------------------------------------------

def check_screwing(
    row: pd.Series,
    line_id: int,
    product_number: int,
    already_screwed: bool,
) -> ScrewCheckResult:
    """Evaluate the simple torque/rotation fastening rule for one sample.

    Fault: target torque must NOT arrive before the required rotation.
    Success: once required rotation exists and target torque is reached, the
    screw fastening operation is accepted.
    """
    torque_nm = float(row["torque_nm"])
    angle_deg = float(row["screw_angle_deg"])
    sample_time_s = float(row["time_s"])

    if torque_nm >= TARGET_TORQUE_NM and angle_deg < REQUIRED_ROTATION_DEG:
        return ScrewCheckResult(
            fault=FaultEvent(
                error_id=ERR_EARLY_TARGET_TORQUE,
                error_message=(
                    "Target torque reached before required screw rotation"
                ),
                station=STATION_FASTENING,
                line_id=line_id,
                product_number=product_number,
                sample_time_s=sample_time_s,
                measurements={
                    "torque_nm": torque_nm,
                    "screw_angle_deg": angle_deg,
                },
            )
        )

    if (
        not already_screwed
        and angle_deg >= REQUIRED_ROTATION_DEG
        and torque_nm >= TARGET_TORQUE_NM
    ):
        return ScrewCheckResult(
            screwing_successful=True,
            acceptance_message=OK_SCREW_FASTENING,
        )

    return ScrewCheckResult()


# ---------------------------------------------------------------------------
# Check 3: no screw / free rotation / invalid engagement
# ---------------------------------------------------------------------------

def check_screw_engagement(
    row: pd.Series,
    line_id: int,
    product_number: int,
) -> CheckResult:
    """Check that the screw exists and the normal torque-angle result is reached.

    A free-rotation/no-screw scenario can later keep the screw sensor low and/or
    let rotation continue without building the required torque. The normal
    golden cycle satisfies all three criteria at 38.0 s.
    """
    sample_time_s = float(row["time_s"])
    if not _at_checkpoint(sample_time_s, ST2_ENGAGEMENT_CHECK_S):
        return CheckResult()

    screw_loaded = float(row["st2_s1_screw_loaded"])
    torque_nm = float(row["torque_nm"])
    angle_deg = float(row["screw_angle_deg"])

    if (
        screw_loaded == 1.0
        and angle_deg >= REQUIRED_ROTATION_DEG
        and torque_nm >= TARGET_TORQUE_NM
    ):
        return CheckResult(
            accepted=True,
            acceptance_message=OK_SCREW_ENGAGEMENT,
        )

    return CheckResult(
        fault=FaultEvent(
            error_id=ERR_NO_SCREW_ENGAGEMENT,
            error_message=(
                "Screw engagement not confirmed: screw presence or required "
                "torque-angle condition is missing"
            ),
            station=STATION_FASTENING,
            line_id=line_id,
            product_number=product_number,
            sample_time_s=sample_time_s,
            measurements={
                "screw_loaded": screw_loaded,
                "torque_nm": torque_nm,
                "screw_angle_deg": angle_deg,
            },
        )
    )


# ---------------------------------------------------------------------------
# Check 4: product stuck / Station 2 exit missing
# ---------------------------------------------------------------------------

def check_station_2_exit(
    row: pd.Series,
    line_id: int,
    product_number: int,
) -> CheckResult:
    """Check that the assembly reaches the expected Station 2 exit event."""
    sample_time_s = float(row["time_s"])
    if not _at_checkpoint(sample_time_s, ST2_EXIT_CHECK_S):
        return CheckResult()

    exit_sensor = float(row["st2_s2_assembly_exit"])

    if exit_sensor == 1.0:
        return CheckResult(
            accepted=True,
            acceptance_message=OK_ST2_EXIT,
        )

    return CheckResult(
        fault=FaultEvent(
            error_id=ERR_PRODUCT_STUCK_NO_EXIT,
            error_message=(
                "Assembly did not leave Station 2 at the expected exit time"
            ),
            station=STATION_FASTENING,
            line_id=line_id,
            product_number=product_number,
            sample_time_s=sample_time_s,
            measurements={"st2_s2_assembly_exit": exit_sensor},
        )
    )


# ---------------------------------------------------------------------------
# Check 5: Station 3 final inspection
# ---------------------------------------------------------------------------

def check_station_3_final_inspection(
    row: pd.Series,
    line_id: int,
    product_number: int,
) -> CheckResult:
    """Check that all six final inspection sensors report OK."""
    sample_time_s = float(row["time_s"])
    if not _at_checkpoint(sample_time_s, ST3_FINAL_CHECK_S):
        return CheckResult()

    sensor_values = {
        f"st3_s{sensor_number}_check": float(row[f"st3_s{sensor_number}_check"])
        for sensor_number in range(1, 7)
    }

    if all(value == 1.0 for value in sensor_values.values()):
        return CheckResult(
            accepted=True,
            acceptance_message=OK_ST3_FINAL_INSPECTION,
        )

    return CheckResult(
        fault=FaultEvent(
            error_id=ERR_FINAL_INSPECTION_FAILED,
            error_message=(
                "Station 3 final inspection failed: one or more final check "
                "sensors are NOK"
            ),
            station=STATION_FINAL_INSPECTION,
            line_id=line_id,
            product_number=product_number,
            sample_time_s=sample_time_s,
            measurements=sensor_values,
        )
    )


# ---------------------------------------------------------------------------
# End-of-cycle guard
# ---------------------------------------------------------------------------

def check_cycle_completion(
    line_id: int,
    product_number: int,
    b_screwed: bool,
) -> FaultEvent | None:
    """Verify that a completed cycle contains a valid fastening result."""
    if b_screwed:
        return None

    return FaultEvent(
        error_id=ERR_SCREW_NOT_COMPLETED,
        error_message="Cycle ended without successful screwing",
        station=STATION_FASTENING,
        line_id=line_id,
        product_number=product_number,
    )


# ---------------------------------------------------------------------------
# Acceptance-test helper
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Unified per-sample evaluation used by the MES runtime
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SampleEvaluationResult:
    """Standardized result of running all current checks for one sample."""

    screwing_successful: bool = False
    acceptance_messages: tuple[str, ...] = ()
    fault: FaultEvent | None = None


def evaluate_sample(
    row: pd.Series,
    line_id: int,
    product_number: int,
    already_screwed: bool,
) -> SampleEvaluationResult:
    """Run all current production checks for one line/sample.

    The MES runtime calls only this function. Concrete detector names and
    station-specific rules therefore remain inside this module.
    """
    acceptance_messages: list[str] = []

    for result in (
        check_station_1_alignment(row, line_id, product_number),
        check_screw_engagement(row, line_id, product_number),
        check_station_2_exit(row, line_id, product_number),
        check_station_3_final_inspection(row, line_id, product_number),
    ):
        if result.fault is not None:
            return SampleEvaluationResult(
                acceptance_messages=tuple(acceptance_messages),
                fault=result.fault,
            )
        if result.accepted:
            acceptance_messages.append(result.acceptance_message)

    screw_result = check_screwing(
        row=row,
        line_id=line_id,
        product_number=product_number,
        already_screwed=already_screwed,
    )
    if screw_result.fault is not None:
        return SampleEvaluationResult(
            acceptance_messages=tuple(acceptance_messages),
            fault=screw_result.fault,
        )

    if screw_result.screwing_successful:
        acceptance_messages.append(screw_result.acceptance_message)

    return SampleEvaluationResult(
        screwing_successful=screw_result.screwing_successful,
        acceptance_messages=tuple(acceptance_messages),
    )


# ---------------------------------------------------------------------------
# Acceptance-test helper
# ---------------------------------------------------------------------------

def evaluate_cycle_acceptance(
    data: pd.DataFrame,
    line_id: int = 1,
    product_number: int = 1,
) -> tuple[list[str], list[FaultEvent]]:
    """Run one complete cycle through all five current production checks."""
    acceptance_messages: list[str] = []
    faults: list[FaultEvent] = []
    already_screwed = False

    for _, row in data.iterrows():
        result = evaluate_sample(
            row=row,
            line_id=line_id,
            product_number=product_number,
            already_screwed=already_screwed,
        )
        acceptance_messages.extend(result.acceptance_messages)

        if result.fault is not None:
            faults.append(result.fault)

        if result.screwing_successful:
            already_screwed = True

    completion_fault = check_cycle_completion(
        line_id=line_id,
        product_number=product_number,
        b_screwed=already_screwed,
    )
    if completion_fault is not None:
        faults.append(completion_fault)

    return acceptance_messages, faults
