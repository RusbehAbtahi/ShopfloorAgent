"""Own and dispatch the seven ShopfloorAgent MCP application tools.

This module is the application boundary behind the MCP runtime. It advertises
MCP metadata for the seven deterministic Shopfloor tools, dispatches calls to
the existing business implementations, and converts their dictionaries into
standard MCP CallToolResult objects. HTTP transport and server lifecycle stay
in server.py.

Main classes:
    ShopfloorMcpApplication:
        Owns the seven deterministic tools and dispatches MCP calls.

Main methods:
    list_tools():
        Returns the seven MCP tool definitions.
    call_tool():
        Executes one named Shopfloor tool and returns an MCP result.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import asdict
from typing import Any

import mcp.types as types
from mcp import MCPError

from calculate_production_impact import (
    CalculateProductionImpactTool,
    SERVER_INSTRUCTIONS as IMPACT_SERVER_INSTRUCTIONS,
    TOOL_NAME as IMPACT_TOOL_NAME,
    tool_metadata as impact_tool_metadata,
)
from get_incident_details import (
    GetIncidentDetailsTool,
    SERVER_INSTRUCTIONS as DETAILS_SERVER_INSTRUCTIONS,
    TOOL_NAME as DETAILS_TOOL_NAME,
    tool_metadata as details_tool_metadata,
)
from get_production_statistics import (
    GetProductionStatisticsTool,
    SERVER_INSTRUCTIONS as STATISTICS_SERVER_INSTRUCTIONS,
    TOOL_NAME as STATISTICS_TOOL_NAME,
    tool_metadata as statistics_tool_metadata,
)
from get_repair_experience import (
    GetRepairExperienceTool,
    SERVER_INSTRUCTIONS as REPAIR_SERVER_INSTRUCTIONS,
    TOOL_NAME as REPAIR_TOOL_NAME,
    tool_metadata as repair_tool_metadata,
)
from get_resolution_instructions import (
    GetResolutionInstructionsTool,
    SERVER_INSTRUCTIONS as RESOLUTION_SERVER_INSTRUCTIONS,
    TOOL_NAME as RESOLUTION_TOOL_NAME,
    tool_metadata as resolution_tool_metadata,
)
from get_status import (
    GetStatusTool,
    SERVER_INSTRUCTIONS as STATUS_SERVER_INSTRUCTIONS,
    TOOL_NAME as STATUS_TOOL_NAME,
    tool_metadata as status_tool_metadata,
)
from list_prior_incidents import (
    ListPriorIncidentsTool,
    SERVER_INSTRUCTIONS as INCIDENTS_SERVER_INSTRUCTIONS,
    TOOL_NAME as INCIDENTS_TOOL_NAME,
    tool_metadata as incidents_tool_metadata,
)
from mcp_tool_contracts import error_result, success_result


SERVER_INSTRUCTIONS = " ".join(
    (
        "You are connected to the ShopfloorAgent MCP server. Use only the tools "
        "exposed by this server and their declared input schemas. Do not invent "
        "tool names, production identifiers, incident IDs, line IDs, station IDs, "
        "error IDs, dates, or other arguments. Explicit values supplied by the "
        "user take precedence over contextual values. Required arguments must be "
        "resolved before a tool call; when a required value cannot be resolved "
        "safely, ask for it rather than inventing it. Tool results are authoritative "
        "shopfloor data and must not be fabricated or silently changed.",
        STATUS_SERVER_INSTRUCTIONS,
        STATISTICS_SERVER_INSTRUCTIONS,
        INCIDENTS_SERVER_INSTRUCTIONS,
        RESOLUTION_SERVER_INSTRUCTIONS,
        REPAIR_SERVER_INSTRUCTIONS,
        IMPACT_SERVER_INSTRUCTIONS,
        DETAILS_SERVER_INSTRUCTIONS,
    )
)

SHOPFLOOR_TOOL_NAMES = frozenset(
    {
        STATUS_TOOL_NAME,
        STATISTICS_TOOL_NAME,
        INCIDENTS_TOOL_NAME,
        RESOLUTION_TOOL_NAME,
        REPAIR_TOOL_NAME,
        IMPACT_TOOL_NAME,
        DETAILS_TOOL_NAME,
    }
)


class ShopfloorMcpApplication:
    """Own the seven Shopfloor tools and expose them through MCP contracts."""

    def __init__(self) -> None:
        self._tools: dict[str, Callable[..., dict[str, Any]]] = {
            STATUS_TOOL_NAME: GetStatusTool().execute,
            STATISTICS_TOOL_NAME: GetProductionStatisticsTool().execute,
            INCIDENTS_TOOL_NAME: ListPriorIncidentsTool().execute,
            RESOLUTION_TOOL_NAME: GetResolutionInstructionsTool().execute,
            REPAIR_TOOL_NAME: GetRepairExperienceTool().execute,
            IMPACT_TOOL_NAME: CalculateProductionImpactTool().execute,
            DETAILS_TOOL_NAME: GetIncidentDetailsTool().execute,
        }

    def list_tools(self) -> list[types.Tool]:
        """Return the seven tools advertised to MCP clients."""
        definitions = (
            status_tool_metadata(),
            statistics_tool_metadata(),
            incidents_tool_metadata(),
            resolution_tool_metadata(),
            repair_tool_metadata(),
            impact_tool_metadata(),
            details_tool_metadata(),
        )
        return [types.Tool.model_validate(item) for item in definitions]

    def call_tool(
        self,
        name: str,
        arguments: Mapping[str, Any] | None,
    ) -> types.CallToolResult:
        """Execute one named tool and return the standard MCP result envelope."""
        execute = self._tools.get(name)
        if execute is None:
            raise MCPError(
                code=types.INVALID_PARAMS,
                message=f"Unknown tool: {name}",
            )
        return self._execute(execute, arguments)

    @staticmethod
    def _execute(
        execute: Callable[..., dict[str, Any]],
        arguments: Mapping[str, Any] | None,
    ) -> types.CallToolResult:
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, Mapping):
            internal_result = error_result("tool arguments must be an object")
            return types.CallToolResult.model_validate(asdict(internal_result))

        try:
            payload = execute(**dict(arguments))
        except (TypeError, ValueError) as error:
            internal_result = error_result(str(error))
        except Exception:  # noqa: BLE001 - sanitize the external MCP boundary
            internal_result = error_result("Shopfloor tool execution failed")
        else:
            if not isinstance(payload, dict):
                internal_result = error_result(
                    "Shopfloor tools must return a dictionary result"
                )
            else:
                internal_result = success_result(payload)

        return types.CallToolResult.model_validate(asdict(internal_result))
