"""Run the ShopfloorAgent MCP runtime over Streamable HTTP.

The server mirrors the proven GHOST MCP boundary for this PoC: Uvicorn hosts
one MCP Streamable HTTP endpoint, the MCP SDK owns protocol negotiation, and
ShopfloorMcpApplication owns the seven deterministic business tools. The
runtime is deliberately local/unauthenticated so the same endpoint can be used
by ProductionAgent directly and exposed through a secure MCP tunnel to ChatGPT.

Main classes:
    ShopfloorMcpRuntime:
        Connects the MCP SDK transport to ShopfloorMcpApplication.

Main functions:
    main():
        Builds the configured runtime and starts Uvicorn.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import anyio
import mcp.types as types
import uvicorn
from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel import Server
from mcp.server.transport_security import TransportSecuritySettings

from mcp_app import SERVER_INSTRUCTIONS, SHOPFLOOR_TOOL_NAMES, ShopfloorMcpApplication


SERVER_NAME = "ShopfloorAgent"
SERVER_VERSION = "1.0.0"
MCP_PATH = "/mcp"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8001
DEFAULT_LOG_LEVEL = "info"
ALLOWED_LOG_LEVELS = {"critical", "error", "warning", "info", "debug", "trace"}
DEFAULT_ALLOWED_HOSTS = (
    "127.0.0.1",
    "127.0.0.1:*",
    "localhost",
    "localhost:*",
    "[::1]",
    "[::1]:*",
)
DEFAULT_ALLOWED_ORIGINS = (
    "http://127.0.0.1:*",
    "http://localhost:*",
    "http://[::1]:*",
)


class ShopfloorMcpRuntime:
    """Connect Shopfloor tools to the MCP Streamable HTTP transport."""

    def __init__(
        self,
        application: ShopfloorMcpApplication,
        transport_security: TransportSecuritySettings,
    ) -> None:
        self.application = application
        self.mcp_server = Server(
            name=SERVER_NAME,
            version=SERVER_VERSION,
            instructions=SERVER_INSTRUCTIONS,
            lifespan=self.lifespan,
            on_list_tools=self.handle_list_tools,
            on_call_tool=self.handle_call_tool_request,
        )
        self.starlette_app = self.mcp_server.streamable_http_app(
            streamable_http_path=MCP_PATH,
            json_response=False,
            stateless_http=False,
            transport_security=transport_security,
        )

    async def handle_list_tools(
        self,
        _context: ServerRequestContext[Any],
        _params: types.PaginatedRequestParams | None,
    ) -> types.ListToolsResult:
        """Return all seven ShopfloorAgent tool definitions."""
        return types.ListToolsResult(tools=self.application.list_tools())

    async def handle_call_tool_request(
        self,
        _context: ServerRequestContext[Any],
        params: types.CallToolRequestParams,
    ) -> types.CallToolResult:
        """Execute one deterministic Shopfloor tool outside the event loop."""
        arguments = dict(params.arguments or {})
        print(
            "[SHOPFLOOR MCP CALL]"
            f" tool={params.name!r} keys={sorted(arguments)}",
            flush=True,
        )
        result = await anyio.to_thread.run_sync(
            self.application.call_tool,
            params.name,
            arguments,
        )
        print(
            "[SHOPFLOOR MCP RESULT]"
            f" tool={params.name!r} is_error={bool(result.is_error)}",
            flush=True,
        )
        return result

    @asynccontextmanager
    async def lifespan(
        self,
        _server: Server[Any],
    ) -> AsyncIterator[dict[str, Any]]:
        """Expose the minimal MCP server lifespan required by this PoC."""
        print(
            f"[SHOPFLOOR MCP START] version={SERVER_VERSION} "
            f"tools={sorted(SHOPFLOOR_TOOL_NAMES)}",
            flush=True,
        )
        try:
            yield {}
        finally:
            print("[SHOPFLOOR MCP STOP]", flush=True)


def _read_host() -> str:
    host = os.getenv("SHOPFLOOR_MCP_HOST", DEFAULT_HOST).strip()
    if not host:
        raise ValueError("SHOPFLOOR_MCP_HOST must not be empty")
    return host


def _read_port() -> int:
    raw_value = os.getenv("SHOPFLOOR_MCP_PORT", str(DEFAULT_PORT))
    try:
        port = int(raw_value)
    except ValueError as error:
        raise ValueError("SHOPFLOOR_MCP_PORT must be an integer") from error
    if not 1 <= port <= 65535:
        raise ValueError("SHOPFLOOR_MCP_PORT must be between 1 and 65535")
    return port


def _read_log_level() -> str:
    value = os.getenv("SHOPFLOOR_MCP_LOG_LEVEL", DEFAULT_LOG_LEVEL).strip().lower()
    if value not in ALLOWED_LOG_LEVELS:
        raise ValueError("SHOPFLOOR_MCP_LOG_LEVEL has an unsupported value")
    return value


def _read_csv_values(name: str, defaults: tuple[str, ...]) -> list[str]:
    raw_value = os.getenv(name)
    if raw_value is None:
        return list(defaults)
    return [item.strip() for item in raw_value.split(",") if item.strip()]


def _create_transport_security() -> TransportSecuritySettings:
    allowed_hosts = _read_csv_values(
        "SHOPFLOOR_MCP_ALLOWED_HOSTS",
        DEFAULT_ALLOWED_HOSTS,
    )
    if not allowed_hosts:
        raise ValueError("SHOPFLOOR_MCP_ALLOWED_HOSTS must not be empty")
    allowed_origins = _read_csv_values(
        "SHOPFLOOR_MCP_ALLOWED_ORIGINS",
        DEFAULT_ALLOWED_ORIGINS,
    )
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=allowed_hosts,
        allowed_origins=allowed_origins,
    )


def main() -> None:
    """Create the Shopfloor MCP server and start Uvicorn."""
    application = ShopfloorMcpApplication()
    runtime = ShopfloorMcpRuntime(
        application=application,
        transport_security=_create_transport_security(),
    )
    config = uvicorn.Config(
        app=runtime.starlette_app,
        host=_read_host(),
        port=_read_port(),
        log_level=_read_log_level(),
    )
    uvicorn.Server(config).run()


if __name__ == "__main__":  # pragma: no cover
    main()
