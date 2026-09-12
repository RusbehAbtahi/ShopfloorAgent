"""Streamlit presentation helpers for the Shopfloor MES.

All GUI widgets live here so the simulation/runtime code remains small.
This module does not contain production-fault criteria.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd
import streamlit as st

from simulation_helpers import build_start_datetime


# Stable GUI label -> controller key mapping. The GUI knows labels only; the
# concrete sensor/torque fault criteria remain in fault_detection.py.
FAULT_BUTTONS = {
    "Stuck Screw / Early Torque": "stuck_screw",
    "Station 1 Alignment": "station1_alignment",
    "No Screw / Free Rotation": "no_screw_engagement",
    "Station 2 No Exit": "station2_no_exit",
    "Final Inspection NOK": "station3_final_inspection",
}


def configure_page() -> None:
    """Configure the Streamlit page and apply a compact industrial theme."""
    st.set_page_config(page_title="Shopfloor MES", layout="centered")

    # Small CSS layer only for visual clarity. The simulation itself stays
    # completely independent from presentation styling.
    st.markdown(
        """
        <style>
        .block-container {
            padding-top: 1.6rem;
            padding-bottom: 2rem;
        }

        /* Compact dark selector: avoids the previous white-on-white field. */
        div[data-baseweb="select"] > div {
            background: #172033 !important;
            border: 1px solid #475569 !important;
            color: #e2e8f0 !important;
            border-radius: 8px !important;
        }
        div[data-baseweb="select"] span {
            color: #e2e8f0 !important;
        }
        div[data-baseweb="select"] svg {
            fill: #94a3b8 !important;
        }
        div[data-baseweb="popover"] ul {
            background: #172033 !important;
            border: 1px solid #475569 !important;
        }
        div[data-baseweb="popover"] li {
            color: #e2e8f0 !important;
        }

        /* Primary action = teal. */
        div[data-testid="stButton"] button[kind="primary"] {
            background: #0f766e !important;
            border-color: #14b8a6 !important;
            color: white !important;
            border-radius: 8px !important;
        }

        /* Fault actions = restrained dark red, not bright warning red. */
        div[data-testid="stButton"] button[kind="secondary"] {
            background: #30181d !important;
            border-color: #7f1d1d !important;
            color: #fecdd3 !important;
            border-radius: 8px !important;
        }
        div[data-testid="stButton"] button[kind="secondary"]:hover {
            background: #452027 !important;
            border-color: #b91c1c !important;
        }
        div[data-testid="stButton"] button:disabled {
            opacity: 0.42 !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.title("Shopfloor MES Simulation")


def render_start_controls() -> tuple[datetime, bool]:
    """Render start-date/time controls and return exact datetime + button state."""
    now = datetime.now().replace(microsecond=0)

    with st.container(border=True):
        st.subheader("Simulation")
        selected_date = st.date_input("Simulation start date", value=now.date())

        # Streamlit time_input cannot use one-second steps, therefore H/M/S are
        # explicit numeric controls.
        col_hour, col_minute, col_second = st.columns(3)
        with col_hour:
            hour = st.number_input(
                "Hour", min_value=0, max_value=23, value=now.hour, step=1
            )
        with col_minute:
            minute = st.number_input(
                "Minute", min_value=0, max_value=59, value=now.minute, step=1
            )
        with col_second:
            second = st.number_input(
                "Second", min_value=0, max_value=59, value=now.second, step=1
            )

        start_datetime = build_start_datetime(
            selected_date,
            int(hour),
            int(minute),
            int(second),
        )

        start_requested = st.button(
            "Start Simulation",
            type="primary",
            width="stretch",
        )

    return start_datetime, start_requested


def show_start_result(started: bool) -> None:
    """Show a minimal message after the Start button is pressed."""
    if started:
        st.success("Simulation started. Progress is printed in the CLI.")
    else:
        st.info("Simulation is already running.")


def render_fault_controls(
    controller: Any,
) -> tuple[int | None, str | None, str]:
    """Always render line selector plus the five deterministic fault buttons."""
    with st.container(border=True):
        st.subheader("Fault Injection")

        selected_line = st.selectbox(
            "Production line",
            options=[1, 2, 3, 4],
            format_func=lambda line_id: f"Line {line_id}",
            width=240,
            key="fault_target_line",
        )

        # Buttons remain visible before simulation start and after line faults.
        # They are enabled only when the currently selected line can accept a
        # new fault. This prevents stacking a second fault onto the same line.
        can_inject = (
            controller is not None
            and controller.can_inject_fault(int(selected_line))
        )

        if controller is None:
            st.caption("Start the simulation to enable fault injection.")
        elif not can_inject:
            st.caption(
                f"Line {int(selected_line)} already has a pending/active fault "
                "or is stopped. Select another running line."
            )
        else:
            st.caption(
                f"Selected target: Line {int(selected_line)}. Choose one fault."
            )

        requested_fault_key: str | None = None
        requested_fault_label = ""

        # Two-column layout keeps the fault panel compact and makes each action
        # visually distinct from the normal Start action.
        fault_items = list(FAULT_BUTTONS.items())
        button_columns = st.columns(2)
        for index, (label, fault_key) in enumerate(fault_items):
            with button_columns[index % 2]:
                if st.button(
                    label,
                    key=f"fault_{fault_key}",
                    disabled=not can_inject,
                    width="stretch",
                    type="secondary",
                ):
                    requested_fault_key = fault_key
                    requested_fault_label = label

        return int(selected_line), requested_fault_key, requested_fault_label


def show_fault_injection_result(
    line_id: int,
    fault_label: str,
    injected: bool,
) -> None:
    """Report whether the selected line accepted the selected fault cycle."""
    if injected:
        st.warning(
            f"{fault_label} loaded for Line {line_id}. "
            "The line will stop when the detector reaches the fault."
        )
    else:
        st.info(
            f"Line {line_id} cannot accept another fault until it is reset/repaired."
        )


def _empty_status_rows() -> list[dict[str, object]]:
    """Return the four visible placeholder rows before simulation starts."""
    return [
        {
            "Line": line_id,
            "Status": "○ READY",
            "Product": "-",
            "Sample": "-",
            "Cycle": "normal_cycle_90s.csv",
            "Screwed": "-",
            "Fault ID": "",
            "Fault": "",
        }
        for line_id in range(1, 5)
    ]


def _style_status_row(row: pd.Series) -> list[str]:
    """Apply a quiet status tint to each complete table row."""
    status = str(row["Status"])
    if "FAULT" in status:
        style = "background-color: #3b161c; color: #fecaca;"
    elif "RUNNING" in status:
        style = "background-color: #102d28; color: #ccfbf1;"
    else:
        style = "background-color: #1e293b; color: #e2e8f0;"
    return [style] * len(row)


@st.fragment(run_every=0.35)
def render_status() -> None:
    """Always show and automatically refresh the four production-line states."""
    controller = st.session_state.get("simulation_controller")

    with st.container(border=True):
        st.subheader("Production Lines")

        if controller is None:
            st.caption("Simulation not started")
            status_rows = _empty_status_rows()
        else:
            status_rows: list[dict[str, object]] = []
            with controller.lock:
                for line in controller.lines.values():
                    if line.fault_active or not line.running:
                        status = "● FAULT"
                    else:
                        status = "● RUNNING"

                    status_rows.append(
                        {
                            "Line": line.line_id,
                            "Status": status,
                            "Product": line.product_number,
                            "Sample": line.sample_index,
                            "Cycle": controller.line_cycle_names[line.line_id],
                            "Screwed": line.b_screwed,
                            "Fault ID": line.fault_id,
                            "Fault": line.fault_message,
                        }
                    )

        status_frame = pd.DataFrame(status_rows)
        styled_frame = status_frame.style.apply(_style_status_row, axis=1)

        st.dataframe(
            styled_frame,
            hide_index=True,
            width="stretch",
            column_config={
                "Line": st.column_config.NumberColumn("Line", width="small"),
                "Status": st.column_config.TextColumn("Status", width="small"),
                "Product": st.column_config.TextColumn("Product", width="small"),
                "Sample": st.column_config.TextColumn("Sample", width="small"),
                "Cycle": st.column_config.TextColumn("Cycle", width="medium"),
                "Screwed": st.column_config.TextColumn("Screwed", width="small"),
                "Fault ID": st.column_config.TextColumn("Fault ID", width="medium"),
                "Fault": st.column_config.TextColumn("Fault", width="large"),
            },
        )
