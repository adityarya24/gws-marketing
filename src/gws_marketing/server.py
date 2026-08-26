"""gws-marketing stdio MCP server.

Binds the registry in :mod:`gws_marketing.tools` to a low-level Model Context
Protocol stdio server, mirroring the astro-skill convention: the registry
stays the single source of truth and schemas are declared explicitly for a
predictable wire contract with any MCP client.
"""
from __future__ import annotations

import asyncio
from typing import Any

import mcp.types as types
from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server

from . import __version__
from .drive import DriveRestClient
from .ga4 import Ga4RestClient
from .gcal import GcalRestClient
from .gmail import GmailRestClient
from .gsc import build_client
from .tools import DESCRIPTIONS, SCHEMAS, TOOLS

SERVER_NAME = "gws-marketing"


def get_client(tool_name: str, account: str = "default") -> Any:
    """Resolve the right client lazily so imports never require OAuth state."""
    from .auth import load_credentials

    credentials = load_credentials(account)
    if credentials is None:
        raise RuntimeError(
            f"No stored Google credentials for account '{account}'. "
            "Call the auth_login tool (or run gws-marketing-login) first."
        )
    if tool_name.startswith("gsc_"):
        return build_client(credentials)
    if tool_name.startswith("gmail_"):
        return GmailRestClient.from_credentials(credentials)
    if tool_name.startswith("gcal_"):
        return GcalRestClient.from_credentials(credentials)
    if tool_name.startswith("drive_"):
        return DriveRestClient.from_credentials(credentials)
    return Ga4RestClient.from_credentials(credentials)


def build_tool_definitions() -> list[types.Tool]:
    return [
        types.Tool(name=name, description=DESCRIPTIONS[name], inputSchema=SCHEMAS[name])
        for name in sorted(SCHEMAS)
    ]


async def handle_call(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
    try:
        handler = TOOLS[name]
    except KeyError as exc:
        raise ValueError(f"Unknown gws-marketing tool: {name}") from exc

    # Auth handlers manage local token storage and need no API client.
    if name.startswith("auth_"):
        client = None
    else:
        account = str(arguments.get("account") or "default")
        client = get_client(name, account)
    # Run handlers in a worker thread: auth_login may block for minutes while
    # the user consents in the browser, and the loop must stay responsive.
    result = await asyncio.to_thread(handler, client, **(arguments or {}))
    import json

    return [types.TextContent(type="text", text=json.dumps(result, indent=2, default=str))]


def create_server() -> Server:
    server = Server(SERVER_NAME)

    @server.list_tools()
    async def _list_tools() -> list[types.Tool]:
        return build_tool_definitions()

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
        return await handle_call(name, arguments)

    return server


async def _run() -> None:
    server = create_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name=SERVER_NAME,
                server_version=__version__,
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
