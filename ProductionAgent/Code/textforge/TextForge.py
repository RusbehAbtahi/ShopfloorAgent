# ragstream/textforge/TextForge.py
# -*- coding: utf-8 -*-
"""
TextForge
=========

Main logging facade.

Responsibilities:
- Hold current/default text, severity type, and sensitivity.
- Generate one unique id for every emitted log entry.
- Route the entry to enabled sinks.
- Stay neutral: no file paths, no GUI policy, no SQLite policy, no Sink0 policy.
"""

from __future__ import annotations

import uuid
from typing import Optional

from ragstream.textforge.TextSink import TextSink


class TextForge:
    """
    Main facade used by application code.

    Typical usage:
        logger = TextForge(...)
        logger("Application started")
        logger("Full prompt stored", "INFO", "CONFIDENTIAL")
    """

    def __init__(
        self,
        text: str = "",
        type: str = "INFO",
        sensitivity: str = "PUBLIC",
        sinks: Optional[list[TextSink]] = None,
        b_enable: Optional[list[bool]] = None,
    ) -> None:
        """
        Initialize current/default text/type/sensitivity and sink routing.

        Args:
            text:
                Current/default text value.
            type:
                Current/default severity type.
            sensitivity:
                Current/default sensitivity flag.
            sinks:
                List of available sink objects.
            b_enable:
                Enable map; b_enable[i] controls sinks[i].
        """
        self.id: str = ""
        self.text: str = text
        self.type: str = type
        self.sensitivity: str = sensitivity

        self.sinks: list[TextSink] = sinks or []

        if b_enable is None:
            self.b_enable: list[bool] = [True] * len(self.sinks)
        else:
            self.b_enable = b_enable

        if len(self.b_enable) != len(self.sinks):
            raise ValueError("b_enable must have the same length as sinks.")

    def __call__(
        self,
        text: Optional[str] = None,
        type: Optional[str] = None,
        sensitivity: Optional[str] = None,
    ) -> None:
        """
        Shortcut for log().

        Allows:
            logger()
            logger("text")
            logger("text", "WARN")
            logger("text", "INFO", "CONFIDENTIAL")
        """
        self.log(text=text, type=type, sensitivity=sensitivity)

    def log(
        self,
        text: Optional[str] = None,
        type: Optional[str] = None,
        sensitivity: Optional[str] = None,
    ) -> None:
        """
        Emit one log entry.

        Behavior:
        1. Update current/default text/type/sensitivity if new values are provided.
        2. Generate a new unique id.
        3. Loop over enabled sinks.
        4. Send id/text/type/sensitivity to each enabled sink.

        TextForge does not know how sinks write.
        File/GUI/CLI/SQLite/thread behavior is inside the sink classes.
        """
        if text is not None:
            self.text = text

        if type is not None:
            self.type = type

        if sensitivity is not None:
            self.sensitivity = sensitivity

        self.id = self._generate_id()

        for sink, enabled in zip(self.sinks, self.b_enable):
            if enabled:
                sink.log(
                    id=self.id,
                    text=self.text,
                    type=self.type,
                    sensitivity=self.sensitivity,
                )

    def _generate_id(self) -> str:
        """
        Create one long unique id for the emitted log entry.

        uuid4().hex gives a 32-character hexadecimal id.
        SQLite can later enforce uniqueness with PRIMARY KEY.
        """
        return uuid.uuid4().hex