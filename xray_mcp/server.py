# Copyright (c) 2026 netcare GmbH. All rights reserved.
# SPDX-License-Identifier: MIT

"""Server factory: selects toolsets from the settings and wires up the Xray client.

Entry points: the ``jira-xray-cloud-mcp`` command (``main``) and
``fastmcp run xray_mcp/server.py:create_server``. Both read the XRAY_* variables
(see config.py); the transport comes from FASTMCP_TRANSPORT / FASTMCP_HOST / FASTMCP_PORT
or the ``fastmcp run`` flags.
"""

from typing import Any

import httpx2
from fastmcp import FastMCP
from fastmcp.server.lifespan import lifespan
from fastmcp.utilities.logging import get_logger
from mcp.types import ToolAnnotations

from xray_mcp.client import XrayClient
from xray_mcp.config import Settings
from xray_mcp.registry import register_tools, select_tools, toolset_parts
from xray_mcp.toolsets import ALL_TOOLSETS

logger = get_logger(__name__)

INSTRUCTIONS = """\
Tools for Xray Test Management for Jira Cloud (tests, preconditions, test sets, test plans,
test executions, test runs, test repository folders, coverage, result imports).
Tools accept Jira issue keys (e.g. CALC-12) or numeric issue ids; test runs and steps use their own ids,
which the get tools return. Status names (PASSED, FAILED, ...) are project-configurable:
see xray_get_statuses. List results are paginated with limit (max 100) and start.
"""


def create_server(
    settings: Settings | None = None, *, transport: httpx2.AsyncBaseTransport | None = None
) -> FastMCP:
    """Build the MCP server. ``transport`` replaces the HTTP transport (used by tests)."""
    settings = settings or Settings()
    selection = select_tools(settings.toolsets, settings.tools, ALL_TOOLSETS)
    if settings.auth_mode == "headers" and (settings.client_id or settings.client_secret):
        logger.warning("XRAY_AUTH_MODE=headers: XRAY_CLIENT_ID / XRAY_CLIENT_SECRET are ignored.")

    @lifespan
    async def xray_lifespan(server: FastMCP):
        client = XrayClient(settings, transport=transport)
        try:
            yield {"xray": client}
        finally:
            await client.aclose()

    mcp = FastMCP(
        "Jira Xray Cloud MCP Server",
        instructions=INSTRUCTIONS + ("\nThe server is read-only: write tools are not available.\n" if settings.read_only else ""),
        lifespan=xray_lifespan,
    )
    registered = register_tools(mcp, selection.tools, read_only=settings.read_only)

    enabled = {part.name for part in selection.parts}
    overview = [
        {
            "name": part.name,
            "group": part.toolset.name,
            "access": part.access,
            "description": part.toolset.description,
            "default": part.toolset.default,
            "enabled": part.name in enabled,
            # Includes tools added and excludes tools removed via XRAY_TOOLS.
            "tools": [spec.name for spec in part.tools if spec.name in registered],
        }
        for part in toolset_parts(ALL_TOOLSETS)
    ]

    @mcp.tool(
        tags={"toolset:meta", "read"},
        annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=False),
    )
    def xray_list_toolsets() -> dict[str, Any]:
        """List all Xray toolsets (read and write halves), which tools are enabled, and whether the server is read-only."""
        return {
            "read_only": settings.read_only,
            "auth_mode": settings.auth_mode,
            "tool_count": len(registered),
            "toolsets": overview,
        }

    return mcp


def main() -> None:
    """Run the server configured from the environment (stdio unless FASTMCP_TRANSPORT says otherwise)."""
    create_server().run()
