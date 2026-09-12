from pathlib import Path

import numpy as np
import pandas as pd

SAMPLE_RATE_HZ = 10
DT_S = 1.0 / SAMPLE_RATE_HZ
CYCLE_DURATION_S = 90.0
CONVEYOR_SPEED_MPS = 0.25

# Simple, deterministic normal fastening profile for the PoC.
SCREW_START_S = 35.0
RUNDOWN_END_S = 37.4
TARGET_TORQUE_REACHED_S = 38.0
TARGET_TORQUE_HOLD_END_S = 39.0
TOOL_RELEASE_END_S = 39.5
SCREW_SPEED_RPM = 300.0
SCREW_SPEED_DEG_PER_S = SCREW_SPEED_RPM * 360.0 / 60.0
RUNDOWN_TORQUE_NM = 1.5
TARGET_TORQUE_NM = 12.0

OUTPUT_CSV = Path(__file__).with_name("normal_cycle_90s.csv")


def active(t: np.ndarray, start: float, end: float) -> np.ndarray:
    """Return a rectangular binary signal active on [start, end)."""
    return ((t >= start) & (t < end)).astype(int)


def build_normal_cycle() -> pd.DataFrame:
    # 0.0 ... 89.9 s -> exactly 900 samples at 10 Hz.
    t = np.arange(0.0, CYCLE_DURATION_S, DT_S)

    conveyor_velocity = np.zeros_like(t)
    moving_windows = [(0.0, 10.0), (20.0, 30.0), (60.0, 70.0), (80.0, 90.0)]
    for start, end in moving_windows:
        conveyor_velocity[(t >= start) & (t < end)] = CONVEYOR_SPEED_MPS

    phase = np.full(t.shape, "", dtype=object)
    phase[(t >= 0.0) & (t < 10.0)] = "transport_to_station_1"
    phase[(t >= 10.0) & (t < 20.0)] = "station_1_positioning"
    phase[(t >= 20.0) & (t < 30.0)] = "transport_to_station_2"
    phase[(t >= 30.0) & (t < 60.0)] = "station_2_fastening"
    phase[(t >= 60.0) & (t < 70.0)] = "transport_to_station_3"
    phase[(t >= 70.0) & (t < 80.0)] = "station_3_final_check"
    phase[(t >= 80.0) & (t < 90.0)] = "finished_product_exit"

    # Station 1: arrival, Part A seated, Part B seated, final alignment OK.
    st1_s0_arrival = active(t, 10.0, 12.0)
    st1_s1_part_a_seated = active(t, 11.0, 19.0)
    st1_s2_part_b_seated = active(t, 11.2, 19.0)
    st1_s3_alignment_ok = active(t, 11.5, 19.0)

    # Station 2: assembly present, screw loaded, assembly leaves station.
    st2_s0_assembly_present = active(t, 30.0, 32.0)
    st2_s1_screw_loaded = active(t, 33.0, TOOL_RELEASE_END_S)
    st2_s2_assembly_exit = active(t, 60.0, 62.0)

    # Deterministic accumulated screwdriver angle.
    screw_angle_deg = np.zeros_like(t)
    rotating = (t >= SCREW_START_S) & (t < RUNDOWN_END_S)
    screw_angle_deg[rotating] = (t[rotating] - SCREW_START_S) * SCREW_SPEED_DEG_PER_S
    final_angle_deg = (RUNDOWN_END_S - SCREW_START_S) * SCREW_SPEED_DEG_PER_S
    screw_angle_deg[t >= RUNDOWN_END_S] = final_angle_deg

    # Deterministic torque profile: ramp to rundown torque, hold, rise to target,
    # hold target briefly, then release to zero.
    torque_nm = np.zeros_like(t)

    ramp_in = (t >= SCREW_START_S) & (t < SCREW_START_S + 0.2)
    torque_nm[ramp_in] = (
        (t[ramp_in] - SCREW_START_S) / 0.2 * RUNDOWN_TORQUE_NM
    )

    rundown = (t >= SCREW_START_S + 0.2) & (t < RUNDOWN_END_S)
    torque_nm[rundown] = RUNDOWN_TORQUE_NM

    tighten = (t >= RUNDOWN_END_S) & (t < TARGET_TORQUE_REACHED_S)
    torque_nm[tighten] = RUNDOWN_TORQUE_NM + (
        (t[tighten] - RUNDOWN_END_S)
        / (TARGET_TORQUE_REACHED_S - RUNDOWN_END_S)
        * (TARGET_TORQUE_NM - RUNDOWN_TORQUE_NM)
    )

    target_hold = (t >= TARGET_TORQUE_REACHED_S) & (t < TARGET_TORQUE_HOLD_END_S)
    torque_nm[target_hold] = TARGET_TORQUE_NM

    release = (t >= TARGET_TORQUE_HOLD_END_S) & (t < TOOL_RELEASE_END_S)
    torque_nm[release] = TARGET_TORQUE_NM * (
        1.0
        - (t[release] - TARGET_TORQUE_HOLD_END_S)
        / (TOOL_RELEASE_END_S - TARGET_TORQUE_HOLD_END_S)
    )

    # Station 3: arrival plus six final binary checks. All are normal/OK.
    st3_s0_arrival = active(t, 70.0, 72.0)
    st3_s1_check = active(t, 71.0, 79.5)
    st3_s2_check = active(t, 71.1, 79.5)
    st3_s3_check = active(t, 71.2, 79.5)
    st3_s4_check = active(t, 71.3, 79.5)
    st3_s5_check = active(t, 71.4, 79.5)
    st3_s6_check = active(t, 71.5, 79.5)

    return pd.DataFrame(
        {
            "time_s": np.round(t, 1),
            "phase": phase,
            "conveyor_velocity_mps": conveyor_velocity,
            "st1_s0_arrival": st1_s0_arrival,
            "st1_s1_part_a_seated": st1_s1_part_a_seated,
            "st1_s2_part_b_seated": st1_s2_part_b_seated,
            "st1_s3_alignment_ok": st1_s3_alignment_ok,
            "st2_s0_assembly_present": st2_s0_assembly_present,
            "st2_s1_screw_loaded": st2_s1_screw_loaded,
            "st2_s2_assembly_exit": st2_s2_assembly_exit,
            "torque_nm": np.round(torque_nm, 3),
            "screw_angle_deg": np.round(screw_angle_deg, 1),
            "st3_s0_arrival": st3_s0_arrival,
            "st3_s1_check": st3_s1_check,
            "st3_s2_check": st3_s2_check,
            "st3_s3_check": st3_s3_check,
            "st3_s4_check": st3_s4_check,
            "st3_s5_check": st3_s5_check,
            "st3_s6_check": st3_s6_check,
        }
    )


def main() -> None:
    df = build_normal_cycle()
    if len(df) != 900:
        raise RuntimeError(f"Expected 900 rows, got {len(df)}")
    df.to_csv(OUTPUT_CSV, index=False)
    print(f"Saved {len(df)} rows to {OUTPUT_CSV}")
    print(f"Columns: {len(df.columns)}")
    print(f"Final screw angle: {df['screw_angle_deg'].max():.1f} deg")
    print(f"Peak torque: {df['torque_nm'].max():.1f} Nm")


if __name__ == "__main__":
    main()
