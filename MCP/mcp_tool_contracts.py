"""Define the shared internal result contract for Shopfloor MCP tools.

The contract is the stable envelope between deterministic Shopfloor tool adapters
and the MCP application. Business payloads stay in structuredContent; MCP text
content is a readable JSON representation of the same payload.

Main classes:
    ShopfloorToolResult:
        Immutable result envelope consumed by the MCP application.

Main functions:
    success_result():
        Wraps a successful structured tool payload.
    error_result():
        Wraps a sanitized MCP-facing tool error.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any


@dataclass(frozen=True)
class ShopfloorToolResult:
    """Carry one deterministic tool result to the MCP application boundary."""

    content: list[dict[str, Any]]
    structuredContent: dict[str, Any]
    isError: bool = False


def success_result(payload: dict[str, Any]) -> ShopfloorToolResult:
    """Wrap one successful business result in the common MCP envelope."""
    return ShopfloorToolResult(
        content=[
            {
                "type": "text",
                "text": json.dumps(payload, ensure_ascii=False, indent=2),
            }
        ],
        structuredContent=payload,
    )


def error_result(reason: str) -> ShopfloorToolResult:
    """Return one sanitized error using the same common MCP envelope."""
    payload = {"error": str(reason)}
    return ShopfloorToolResult(
        content=[{"type": "text", "text": f"Shopfloor tool failed: {reason}"}],
        structuredContent=payload,
        isError=True,
     )
