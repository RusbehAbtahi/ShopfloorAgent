"""Strict deterministic fast path for ProductionAgent tool selection."""

from __future__ import annotations

import re

from ...state import ToolName


_TOOL_CALL_PATTERN = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*\(")


class DeterministicSelector:
    """Recognize an explicit canonical Python-like tool call without an LLM."""

    def select(self, request: str) -> ToolName | None:
        """Return the canonical tool name when strict syntax matches, else ``None``."""
        match = _TOOL_CALL_PATTERN.match(str(request or ""))
        if match is None:
            return None

        try:
            return ToolName(match.group(1))
        except ValueError:
            return None
