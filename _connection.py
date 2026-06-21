"""
MCP connection manager for the skill-mcp plugin.

Manages MCP client sessions per (skill_name, mcp_name) pair.
Uses stdio transport for command-based MCP servers.
"""
import asyncio
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any, Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def _client_key(skill_name: str, mcp_name: str) -> str:
    """Build cache key for a (skill, mcp) pair."""
    return f"{skill_name}::{mcp_name}"


def _build_server_params(server_config: dict) -> StdioServerParameters:
    """Build server params from config dict."""
    command = server_config["command"]
    args = _extract_args(server_config)
    env_vars = _extract_env(server_config)
    return StdioServerParameters(
        command=command,
        args=args,
        env=env_vars,
    )


def _extract_args(server_config: dict) -> list:
    """Extract optional args list from server config."""
    if "args" not in server_config:
        return []
    return list(server_config["args"])


def _extract_env(server_config: dict) -> Optional[dict]:
    """Extract optional env dict from server config."""
    if "env" not in server_config:
        return None
    return dict(server_config["env"])


async def _close_connection_safely(conn: "McpConnection") -> None:
    """Safely close a single connection, suppressing expected errors."""
    with suppress(Exception):
        if conn._session_ctx is not None:
            await conn._session_ctx.__aexit__(None, None, None)
    with suppress(Exception):
        if conn._transport_ctx is not None:
            await conn._transport_ctx.__aexit__(None, None, None)


@dataclass
class McpConnection:
    """Active MCP client connection with lazy initialization."""
    session: Optional[ClientSession] = None
    server_params: Optional[StdioServerParameters] = None
    tools: dict[str, Any] = field(default_factory=dict)
    _transport_ctx: Any = field(default=None, repr=False)
    _session_ctx: Any = field(default=None, repr=False)


class SkillMcpManager:
    """Manages MCP client connections per (skill_name, mcp_name)."""

    def __init__(self) -> None:
        self._clients: dict[str, McpConnection] = {}

    def get_or_create_client(
        self,
        skill_name: str,
        mcp_name: str,
        server_config: dict,
    ) -> McpConnection:
        """Get existing or create new MCP client connection."""
        key = _client_key(skill_name, mcp_name)
        existing = self._clients.get(key)
        if existing is not None:
            return existing
        conn = McpConnection(
            server_params=_build_server_params(server_config),
        )
        self._clients[key] = conn
        return conn

    async def connect(self, conn: McpConnection) -> ClientSession:
        """Establish MCP session (idempotent)."""
        if conn.session is not None:
            return conn.session

        conn._transport_ctx = stdio_client(conn.server_params)
        read_stream, write_stream = await conn._transport_ctx.__aenter__()

        conn._session_ctx = ClientSession(read_stream, write_stream)
        session = await conn._session_ctx.__aenter__()
        await session.initialize()

        conn.session = session
        tools_response = await session.list_tools()
        conn.tools = {
            tool_def.name: tool_def
            for tool_def in tools_response.tools
        }
        return session

    async def call_tool(
        self,
        skill_name: str,
        mcp_name: str,
        server_config: dict,
        tool_name: str,
        arguments: Optional[dict] = None,
    ) -> Any:
        """Connect to MCP server and call a tool."""
        conn = self.get_or_create_client(skill_name, mcp_name, server_config)
        session = await self.connect(conn)
        tool_response = await session.call_tool(
            tool_name, arguments or {},
        )
        return tool_response

    async def close(self) -> None:
        """Close all MCP connections concurrently."""
        close_coros = [
            _close_connection_safely(conn)
            for conn in self._clients.values()
        ]
        if close_coros:
            await asyncio.gather(*close_coros, return_exceptions=True)
        self._clients.clear()
