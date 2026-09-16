# ragstream/textforge/TextSink.py
# -*- coding: utf-8 -*-
"""
TextSink
========

Common sink base class.

Responsibilities:
- Define accepted severity types.
- Define accepted sensitivity flags.
- Hold the central LOG_TYPE_CATALOG and SENSITIVITY_CATALOG.
- Format final text using sink_kind-specific prefix/suffix.
- Leave real output to concrete sinks.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional


class TextSink(ABC):
    """
    Base class for all concrete sinks.

    Concrete subclasses:
        FileSink
        GuiSink
        CliSink
    """

    LOG_TYPE_CATALOG: dict[str, dict[str, str]] = {
        "TRACE": {
            "file_prefix": "[TRACE] ",
            "file_suffix": "",
            "gui_prefix": "",
            "gui_suffix": "",
            "cli_prefix": "[TRACE] ",
            "cli_suffix": "",
        },
        "DEBUG": {
            "file_prefix": "[DEBUG] ",
            "file_suffix": "",
            "gui_prefix": "",
            "gui_suffix": "",
            "cli_prefix": "[DEBUG] ",
            "cli_suffix": "",
        },
        "INFO": {
            "file_prefix": "[INFO] ",
            "file_suffix": "",
            "gui_prefix": "",
            "gui_suffix": "",
            "cli_prefix": "[INFO] ",
            "cli_suffix": "",
        },
        "WARN": {
            "file_prefix": "[WARN] ",
            "file_suffix": "",
            "gui_prefix": "Warning: ",
            "gui_suffix": "",
            "cli_prefix": "[WARN] ",
            "cli_suffix": "",
        },
        "ERROR": {
            "file_prefix": "[ERROR] ",
            "file_suffix": "",
            "gui_prefix": "Error: ",
            "gui_suffix": "",
            "cli_prefix": "[ERROR] ",
            "cli_suffix": "",
        },
        "FATAL": {
            "file_prefix": "[FATAL] ",
            "file_suffix": "",
            "gui_prefix": "Fatal error: ",
            "gui_suffix": "",
            "cli_prefix": "[FATAL] ",
            "cli_suffix": "",
        },
    }

    SENSITIVITY_CATALOG: dict[str, dict[str, str]] = {
        "PUBLIC": {
            "meaning": "Safe for normal GUI messages, ordinary CLI output, and general logs.",
        },
        "INTERNAL": {
            "meaning": "Developer/team diagnostic information; not secret, but not normal user-facing.",
        },
        "CONFIDENTIAL": {
            "meaning": "Developer-analysis material that may contain user/project content.",
        },
        "HIGHLY_CONFIDENTIAL": {
            "meaning": "Exceptional class; normally should not be logged.",
        },
    }

    def __init__(
        self,
        sink_kind: Optional[str],
        accept_types: list[str],
        accept_sensitivities: list[str],
        b_timestamp: bool = True,
        b_prefix: bool = True,
        b_suffix: bool = False,
    ) -> None:
        """
        Initialize common sink filtering and formatting options.

        Args:
            sink_kind:
                One of "file", "gui", "cli"; subclasses set this.
            accept_types:
                Severity types this sink accepts.
            accept_sensitivities:
                Sensitivity flags this sink accepts.
            b_timestamp:
                If True, include timestamp in final text.
            b_prefix:
                If True, include prefix from LOG_TYPE_CATALOG.
            b_suffix:
                If True, include suffix from LOG_TYPE_CATALOG.
        """
        self.sink_kind: Optional[str] = sink_kind
        self.accept_types: list[str] = accept_types
        self.accept_sensitivities: list[str] = accept_sensitivities

        self.b_timestamp: bool = b_timestamp
        self.b_prefix: bool = b_prefix
        self.b_suffix: bool = b_suffix

    def accepts(self, type: str, sensitivity: str) -> bool:
        """
        Return True only if both severity type and sensitivity are accepted.
        """
        return (
            type in self.accept_types
            and sensitivity in self.accept_sensitivities
        )

    def _format_text(
        self,
        id: str,
        text: str,
        type: str,
        sensitivity: str,
    ) -> str:
        """
        Build the final text for this sink.

        Formatting belongs here because all sinks share the same logic,
        but each sink_kind uses its own prefix/suffix group.

        Args:
            id:
                Unique log id.
            text:
                Raw user/application log text.
            type:
                Severity type.
            sensitivity:
                Sensitivity flag.

        Returns:
            Final formatted text for the concrete sink.
        """
        catalog_entry = self.LOG_TYPE_CATALOG.get(type, {})

        prefix = ""
        suffix = ""

        if self.sink_kind:
            if self.b_prefix:
                prefix = catalog_entry.get(f"{self.sink_kind}_prefix", "")

            if self.b_suffix:
                suffix = catalog_entry.get(f"{self.sink_kind}_suffix", "")

        parts: list[str] = []

        if self.b_timestamp:
            timestamp = datetime.now().isoformat(timespec="seconds")
            parts.append(f"[{timestamp}]")

        # id and sensitivity are intentionally not forced into the visible text.
        # They are passed to sinks and can be stored in SQLite metadata.
        parts.append(f"{prefix}{text}{suffix}")

        return " ".join(parts)

    @abstractmethod
    def log(
        self,
        id: str,
        text: str,
        type: str,
        sensitivity: str,
    ) -> None:
        """
        Common sink interface.

        Concrete sinks implement the real output action.
        """
        raise NotImplementedError