# ragstream/textforge/GUISink.py
# -*- coding: utf-8 -*-
"""
GuiSink
=======

Concrete sink for Streamlit GUI output.

Responsibilities:
- Accept/reject by severity type and sensitivity.
- Format final text through TextSink.
- Write final text into session_state[key].

Important:
- This sink is Streamlit-specific.
- It is not RAGstream-specific.
"""

from __future__ import annotations

from typing import Literal

from ragstream.textforge.TextSink import TextSink


class GuiSink(TextSink):
    """
    Streamlit GUI sink.

    The actual GUI rendering is not done here.
    This class only writes text into session_state[key].

    ui_layout.py can then display:
        st.session_state["textforge_gui_log"]
    """

    def __init__(
        self,
        session_state: object,
        key: str,
        accept_types: list[str],
        accept_sensitivities: list[str],
        display_mode: Literal["prepend", "append", "replace"] = "prepend",
        b_timestamp: bool = True,
        b_prefix: bool = True,
        b_suffix: bool = False,
    ) -> None:
        """
        Initialize GUI sink.

        Args:
            session_state:
                Streamlit session_state object or compatible mapping.
            key:
                session_state key where GUI log text is stored.
            accept_types:
                Severity types this sink accepts.
            accept_sensitivities:
                Sensitivity flags this sink accepts.
            display_mode:
                prepend = newest message on top
                append  = newest message at bottom
                replace = only latest message
        """
        super().__init__(
            sink_kind="gui",
            accept_types=accept_types,
            accept_sensitivities=accept_sensitivities,
            b_timestamp=b_timestamp,
            b_prefix=b_prefix,
            b_suffix=b_suffix,
        )

        if display_mode not in {"prepend", "append", "replace"}:
            raise ValueError("display_mode must be 'prepend', 'append', or 'replace'.")

        self.session_state: object = session_state
        self.key: str = key
        self.display_mode: Literal["prepend", "append", "replace"] = display_mode

        if self.key not in self.session_state:
            self.session_state[self.key] = ""

    def log(
        self,
        id: str,
        text: str,
        type: str,
        sensitivity: str,
    ) -> None:
        """
        Write one accepted log entry into session_state[key].
        """
        if not self.accepts(type=type, sensitivity=sensitivity):
            return

        final_text = self._format_text(
            id=id,
            text=text,
            type=type,
            sensitivity=sensitivity,
        )

        current_text = self.session_state.get(self.key, "")

        if self.display_mode == "replace":
            self.session_state[self.key] = final_text

        elif self.display_mode == "append":
            if current_text:
                self.session_state[self.key] = f"{current_text}\n{final_text}"
            else:
                self.session_state[self.key] = final_text

        else:  # prepend
            if current_text:
                self.session_state[self.key] = f"{final_text}\n{current_text}"
            else:
                self.session_state[self.key] = final_text