"""Prepare deterministic response data from the raw tool result.

The raw tool result remains authoritative in current_tool_result. RESPONSE gets a
separate presentation copy, so large diagnostic evidence such as incident
snapshots can stay available to the graph without being dumped into the GUI.

Main classes:
    PostProcessingNode:
        Creates the presentation hand-off without altering raw MCP/MES evidence.

Main methods:
    run():
        Builds response_payload and updates current open-incident focus when known.
"""

from __future__ import annotations

from copy import deepcopy
import re
from typing import Any

from ..state import AgentState, Phase, ToolName


class PostProcessingNode:
    """Convert a successful raw tool result into the response hand-off payload."""

    def run(self, state: AgentState) -> dict[str, Any]:
        """Prepare compact display data while preserving the complete raw result."""
        if state["phase"] != Phase.TOOL_DONE:
            raise RuntimeError("POST_PROCESSING requires phase TOOL_DONE.")

        result = state.get("current_tool_result")
        if result is None:
            raise RuntimeError("POST_PROCESSING requires current_tool_result.")

        current_tool = state.get("current_tool")
        updates: dict[str, Any] = {
            "response_payload": {
                "kind": "tool_result",
                "data": self._response_data(
                    current_tool,
                    result,
                    str(state.get("current_request") or ""),
                ),
            }
        }

        if current_tool == ToolName.GET_STATUS:
            updates["open_incidents"] = self._open_incident_ids(result)

        return updates

    @staticmethod
    def _response_data(
        current_tool: ToolName | None,
        result: dict[str, Any],
        current_request: str,
    ) -> dict[str, Any]:
        """Remove bulky incident snapshots only from the GUI presentation copy."""
        display_result = deepcopy(result)

        if current_tool == ToolName.GET_STATUS:
            for incident in display_result.get("incidents", []) or []:
                if isinstance(incident, dict):
                    incident.pop("snapshot", None)

        elif current_tool == ToolName.GET_INCIDENT_DETAILS:
            incident = display_result.get("incident")
            if isinstance(incident, dict):
                incident.pop("snapshot", None)

        elif current_tool == ToolName.LIST_PRIOR_INCIDENTS and _requests_latest_incident(current_request):
            # Added on 16.09.2026: list_prior_incidents is newest-first, so singular latest intent keeps only item one.
            incidents = display_result.get("incidents")
            if isinstance(incidents, list):
                display_result["incidents"] = incidents[:1]

        return display_result

    @staticmethod
    def _open_incident_ids(result: dict[str, Any]) -> list[str]:
        """Project get_status output into the persistent open_incidents field."""
        if bool(result.get("b_ok")):
            return []

        incident_ids: list[str] = []
        for incident in result.get("incidents", []) or []:
            if not isinstance(incident, dict):
                continue
            incident_id = str(incident.get("incident_id") or "").strip()
            if incident_id and incident_id not in incident_ids:
                incident_ids.append(incident_id)
        return incident_ids


def _requests_latest_incident(request: str) -> bool:
    """Return True only for explicit singular latest/last incident wording."""
    text = " ".join(str(request or "").lower().split())
    return re.search(r"\b(?:last|latest|most recent)\s+incident\b", text) is not None
