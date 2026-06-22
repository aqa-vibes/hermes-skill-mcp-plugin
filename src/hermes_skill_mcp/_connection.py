"""MCP connection manager for hermes-skill-mcp plugin.

Manages persistent MCP client sessions per
(session_id, skill_name, mcp_name) triple.
Lazy connect, cache reuse, HTTP/StreamableHTTP + stdio transport,
idle cleanup, concurrent locking, capability checking,
crash recovery.
"""

# flake8: noqa: WPS202

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any


logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_IDLE_TIMEOUT = 300.0
_DEFAULT_CONNECT_TIMEOUT = 10.0
_DEFAULT_TOOL_TIMEOUT = 60.0

_KEY_IDLE_TIMEOUT = "idle_timeout"
_KEY_CONNECT_TIMEOUT = "connect_timeout"
_KEY_TIMEOUT = "timeout"
_KEY_URL = "url"
_KEY_COMMAND = "command"
_KEY_ARGS = "args"
_KEY_ENV = "env"
_KEY_HEADERS = "headers"
_KEY_TYPE = "type"

# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------


@dataclass
class McpConnection:
    """Active MCP client connection with lazy initialization."""

    session: Any = None
    server_config: dict = field(default_factory=dict)
    skill_name: str = ""
    mcp_name: str = ""
    tools: dict[str, Any] = field(default_factory=dict)
    _transport_ctx: Any = field(default=None, repr=False)
    _session_ctx: Any = field(default=None, repr=False)


# ---------------------------------------------------------------------------
# Key / args / lock helpers
# ---------------------------------------------------------------------------


def _client_key(
    session_id: str, skill_name: str, mcp_name: str,
) -> str:
    """Build cache key for a (session, skill, mcp) triple."""
    return f"{session_id}:{skill_name}:{mcp_name}"


def _extract_args(server_config: dict) -> list:
    """Extract optional args list from server config."""
    raw_args = server_config.get(_KEY_ARGS)
    if raw_args is None:
        return []
    return list(raw_args)


def _ensure_lock(
    locks: dict[str, asyncio.Lock], key: str,
) -> asyncio.Lock:
    """Get or create an ``asyncio.Lock`` for the given key."""
    if key not in locks:
        locks[key] = asyncio.Lock()
    return locks[key]


async def _close_connection_safely(conn: McpConnection) -> None:
    """Safely close a single connection, suppressing expected errors."""
    with suppress(BaseException):
        if conn._session_ctx is not None:
            await conn._session_ctx.__aexit__(None, None, None)
    with suppress(BaseException):
        if conn._transport_ctx is not None:
            await conn._transport_ctx.__aexit__(None, None, None)


# ---------------------------------------------------------------------------
# MCP SDK lazy import — returns a dict of types (avoids long tuples)
# ---------------------------------------------------------------------------


def _import_mcp():
    """Import MCP modules lazily, return type dict.

    Returns dict with keys: client_cls, server_params_cls,
    stdio_client_fn, http_client_fn, sse_client_fn,
    read_req_cls, get_prompt_cls.
    """
    try:
        from mcp import (  # noqa: WPS433
            ClientSession, StdioServerParameters,
        )
        from mcp.client.stdio import stdio_client
        from mcp.client.streamable_http import (
            streamablehttp_client,
        )
        from mcp.client.sse import sse_client
        from mcp.types import GetPromptRequest, ReadResourceRequest
    except ImportError as exc:
        raise RuntimeError(
            "MCP SDK not installed. Run: pip install mcp",
        ) from exc

    return {
        "client_cls": ClientSession,
        "server_params_cls": StdioServerParameters,
        "stdio_client_fn": stdio_client,
        "http_client_fn": streamablehttp_client,
        "sse_client_fn": sse_client,
        "read_req_cls": ReadResourceRequest,
        "get_prompt_cls": GetPromptRequest,
    }

# ---------------------------------------------------------------------------
# Connection establishment helpers
# ---------------------------------------------------------------------------


def _check_command_allowed(command: str, mcp_name: str) -> None:
    """Raise if command is denied for MCP server."""
    from hermes_skill_mcp._security import is_command_allowed

    if not is_command_allowed(command):
        raise RuntimeError(
            f"Command '{command}' is not allowed"
            f" for MCP server '{mcp_name}'",
        )


async def _initialize_session(session: Any, mcp_name: str) -> None:
    """Initialize MCP session and verify tools capability."""
    init_result = await session.initialize()
    capabilities = init_result.capabilities
    if capabilities is None or capabilities.tools is None:
        raise RuntimeError(
            f"MCP server '{mcp_name}' does not"
            f" support tools capability.",
        )


async def _create_stdio_session(
    conn: McpConnection, server_config: dict,
) -> Any:
    """Create an MCP session over stdio transport."""
    mcp_types = _import_mcp()

    command = server_config[_KEY_COMMAND]
    _check_command_allowed(command, conn.mcp_name)

    from hermes_skill_mcp._security import filter_mcp_environment

    env = filter_mcp_environment(server_config.get(_KEY_ENV, {}))
    params = mcp_types["server_params_cls"](
        command=command,
        args=_extract_args(server_config),
        env=env,
    )
    conn._transport_ctx = mcp_types["stdio_client_fn"](params)
    read_stream, write_stream = (
        await conn._transport_ctx.__aenter__()
    )
    conn._session_ctx = mcp_types["client_cls"](
        read_stream, write_stream,
    )
    session = await conn._session_ctx.__aenter__()
    await _initialize_session(session, conn.mcp_name)
    return session


async def _create_http_session(
    conn: McpConnection, server_config: dict,
) -> Any:
    """Create an MCP session over HTTP/StreamableHTTP transport."""
    mcp_types = _import_mcp()

    url = server_config[_KEY_URL]
    headers = server_config.get(_KEY_HEADERS, {})
    timeout = server_config.get(
        _KEY_CONNECT_TIMEOUT, _DEFAULT_CONNECT_TIMEOUT,
    )
    conn._transport_ctx = mcp_types["http_client_fn"](
        url, headers=headers, timeout=timeout,
    )
    read_stream, write_stream, _sess_id = (
        await conn._transport_ctx.__aenter__()
    )
    conn._session_ctx = mcp_types["client_cls"](
        read_stream, write_stream,
    )
    session = await conn._session_ctx.__aenter__()
    await _initialize_session(session, conn.mcp_name)
    return session


async def _create_sse_session(
    conn: McpConnection, server_config: dict,
) -> Any:
    """Create an MCP session over SSE transport."""
    mcp_types = _import_mcp()

    url = server_config[_KEY_URL]
    headers = server_config.get(_KEY_HEADERS, {})
    timeout = server_config.get(
        _KEY_CONNECT_TIMEOUT, _DEFAULT_CONNECT_TIMEOUT,
    )
    conn._transport_ctx = mcp_types["sse_client_fn"](
        url, headers=headers, timeout=timeout,
    )
    read_stream, write_stream = (
        await conn._transport_ctx.__aenter__()
    )
    conn._session_ctx = mcp_types["client_cls"](
        read_stream, write_stream,
    )
    session = await conn._session_ctx.__aenter__()
    await _initialize_session(session, conn.mcp_name)
    return session

async def _establish_connection(
    manager: SkillMcpManager,
    conn: McpConnection,
    conn_key: str,
) -> Any:
    """Route to stdio or HTTP, init, cache tools, schedule idle."""
    try:
        server_config = conn.server_config
        entry_type = server_config.get(_KEY_TYPE)

        if entry_type == "sse":
            session = await _create_sse_session(conn, server_config)
        elif _KEY_URL in server_config:
            session = await _create_http_session(conn, server_config)
        else:
            session = await _create_stdio_session(conn, server_config)

        conn.session = session
        tools_resp = await session.list_tools()
        conn.tools = {
            tool_def.name: tool_def
            for tool_def in tools_resp.tools
        }
        _reschedule_idle(manager, conn_key, server_config)
        logger.info(
            "MCP connection established: %s (skill=%s, mcp=%s)",
            conn_key, conn.skill_name, conn.mcp_name,
        )
        return session
    except Exception:
        manager._clients.pop(conn_key, None)
        await _close_connection_safely(conn)
        raise


# ---------------------------------------------------------------------------
# Idle cleanup helpers
# ---------------------------------------------------------------------------


def _reschedule_idle(
    manager: SkillMcpManager,
    conn_key: str,
    server_config: dict,
) -> None:
    """Reset idle disconnect timer using config's idle_timeout."""
    idle_timeout = server_config.get(
        _KEY_IDLE_TIMEOUT, _DEFAULT_IDLE_TIMEOUT,
    )
    _schedule_idle_disconnect(
        manager._idle_tasks, manager._clients, manager._locks,
        conn_key, idle_timeout,
    )


def _schedule_idle_disconnect(
    idle_tasks: dict[str, asyncio.Task[None]],
    clients: dict[str, McpConnection],
    locks: dict[str, asyncio.Lock],
    conn_key: str,
    idle_timeout: float,
) -> None:
    """Schedule or reset idle disconnect timer for a key."""
    if idle_timeout <= 0:
        return
    existing = idle_tasks.pop(conn_key, None)
    if existing is not None:
        existing.cancel()
    task = asyncio.create_task(
        _idle_worker(clients, idle_tasks, locks, conn_key, idle_timeout),
    )
    idle_tasks[conn_key] = task


async def _idle_worker(
    clients: dict[str, McpConnection],
    idle_tasks: dict[str, asyncio.Task[None]],
    locks: dict[str, asyncio.Lock],
    conn_key: str,
    idle_timeout: float,
) -> None:
    """Wait for idle timeout, then disconnect if still cached."""
    try:
        await asyncio.sleep(idle_timeout)
    except asyncio.CancelledError:
        return
    if conn_key not in clients:
        return
    if idle_tasks.get(conn_key) is not asyncio.current_task():
        return
    conn = clients.pop(conn_key, None)
    idle_tasks.pop(conn_key, None)
    locks.pop(conn_key, None)
    if conn is not None:
        await _close_connection_safely(conn)
        logger.debug("MCP connection idle-cleaned: %s", conn_key)


# ---------------------------------------------------------------------------
# Tool / resource / prompt execution helpers
# ---------------------------------------------------------------------------


async def _execute_tool_call(
    session: Any,
    tool_name: str,
    arguments: dict | None,
    mcp_name: str,
    server_config: dict,
    manager: SkillMcpManager,
    conn_key: str,
) -> Any:
    """Execute a tool call with timeout and crash recovery."""
    tool_timeout = server_config.get(
        _KEY_TIMEOUT, _DEFAULT_TOOL_TIMEOUT,
    )
    try:
        return await asyncio.wait_for(
            session.call_tool(tool_name, arguments or {}),
            timeout=tool_timeout,
        )
    except asyncio.TimeoutError:
        raise RuntimeError(
            f"Tool '{tool_name}' timed out after"
            f" {tool_timeout}s on MCP server '{mcp_name}'."
        ) from None
    except Exception:
        conn = manager._clients.pop(conn_key, None)
        if conn is not None:
            await _close_connection_safely(conn)
        raise


async def _execute_resource_read(
    session: Any,
    resource_name: str,
    manager: SkillMcpManager,
    conn_key: str,
) -> Any:
    """Read an MCP resource with crash recovery."""
    mcp_types = _import_mcp()
    try:
        return await session.read_resource(
            mcp_types["read_req_cls"](uri=resource_name),
        )
    except Exception:
        conn = manager._clients.pop(conn_key, None)
        if conn is not None:
            await _close_connection_safely(conn)
        raise


async def _execute_prompt_get(
    session: Any,
    prompt_name: str,
    arguments: dict | None,
    manager: SkillMcpManager,
    conn_key: str,
) -> Any:
    """Get an MCP prompt with crash recovery."""
    mcp_types = _import_mcp()
    try:
        return await session.get_prompt(
            mcp_types["get_prompt_cls"](
                name=prompt_name, arguments=arguments or {},
            ),
        )
    except Exception:
        conn = manager._clients.pop(conn_key, None)
        if conn is not None:
            await _close_connection_safely(conn)
        raise


# ---------------------------------------------------------------------------
# Module-level public helpers (resource / prompt)
# ---------------------------------------------------------------------------


async def call_resource(
    manager: SkillMcpManager,
    skill_name: str,
    mcp_name: str,
    server_config: dict,
    resource_name: str,
    session_id: str = "",
) -> Any:
    """Connect to MCP server and read a resource."""
    session = await manager.get_or_create_client(
        skill_name, mcp_name, server_config, session_id=session_id,
    )
    conn_key = _client_key(session_id, skill_name, mcp_name)
    _reschedule_idle(manager, conn_key, server_config)
    return await _execute_resource_read(
        session, resource_name, manager, conn_key,
    )


async def call_prompt(
    manager: SkillMcpManager,
    skill_name: str,
    mcp_name: str,
    server_config: dict,
    prompt_name: str,
    arguments: dict | None = None,
    session_id: str = "",
) -> Any:
    """Connect to MCP server and get a prompt."""
    session = await manager.get_or_create_client(
        skill_name, mcp_name, server_config, session_id=session_id,
    )
    conn_key = _client_key(session_id, skill_name, mcp_name)
    _reschedule_idle(manager, conn_key, server_config)
    return await _execute_prompt_get(
        session, prompt_name, arguments, manager, conn_key,
    )


# ---------------------------------------------------------------------------
# Connection Manager
# ---------------------------------------------------------------------------


class SkillMcpManager:
    """Manages MCP client connections per session/skill/mcp.

    Connections are keyed by ``{session_id}:{skill_name}:{mcp_name}``.
    Each connection is held open so that both the transport and the
    ClientSession stay alive across multiple tool calls.

    MCP SDK imports are deferred — no import error at module load
    time if the ``mcp`` package is not installed.
    """

    def __init__(self) -> None:
        self._clients: dict[str, McpConnection] = {}
        self._cache = self._clients  # legacy alias
        self._locks: dict[str, asyncio.Lock] = {}
        self._idle_tasks: dict[str, asyncio.Task[None]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_or_create_client(
        self,
        arg1: str,
        arg2: str,
        arg3: str | dict,
        arg4: dict | None = None,
        *,
        session_id: str | None = None,
    ) -> Any:
        """Get or create connected MCP client session.

        Supports two call signatures:
        - (session_id, skill_name, mcp_name, config) — 4 args, legacy
        - (skill_name, mcp_name, server_config) — 3 args, current
        Returns an initialized ClientSession.
        """
        if arg4 is not None:
            actual_sid, skill_nm, mcp_nm, srv_conf = (
                arg1, arg2, arg3, arg4
            )
        elif session_id is not None:
            skill_nm, mcp_nm, srv_conf = arg1, arg2, arg3
            actual_sid = session_id
        else:
            skill_nm, mcp_nm, srv_conf = arg1, arg2, arg3
            actual_sid = ""
        conn_key = _client_key(actual_sid, skill_nm, mcp_nm)
        existing = self._clients.get(conn_key)
        if existing is not None and existing.session is not None:
            return existing.session
        conn = existing or McpConnection(
            server_config=srv_conf,
            skill_name=skill_nm,
            mcp_name=mcp_nm,
        )
        self._clients[conn_key] = conn
        return await self._connect_and_return(conn, conn_key, actual_sid)

    async def _connect_and_return(
        self, conn: McpConnection, conn_key: str,
        session_id: str,
    ) -> Any:
        """Connect and return session, with lock."""
        lock = _ensure_lock(self._locks, conn_key)
        async with lock:
            if conn.session is not None:
                return conn.session
            return await _establish_connection(self, conn, conn_key)

    async def connect(
        self,
        conn: McpConnection,
        session_id: str = "",
    ) -> Any:
        """Establish MCP session (idempotent)."""
        if conn.session is not None:
            return conn.session

        conn_key = _client_key(
            session_id, conn.skill_name, conn.mcp_name,
        )
        lock = _ensure_lock(self._locks, conn_key)
        async with lock:
            if conn.session is not None:
                return conn.session
            return await _establish_connection(self, conn, conn_key)

    async def call_tool(
        self,
        skill_name: str,
        mcp_name: str,
        server_config: dict,
        tool_name: str,
        arguments: dict | None = None,
        session_id: str = "",
    ) -> Any:
        """Connect to MCP server and call a tool."""
        session = await self.get_or_create_client(
            skill_name, mcp_name, server_config, session_id=session_id,
        )
        conn_key = _client_key(session_id, skill_name, mcp_name)
        _reschedule_idle(self, conn_key, server_config)
        return await _execute_tool_call(
            session, tool_name, arguments, mcp_name,
            server_config, self, conn_key,
        )

    async def shutdown_all(self) -> None:
        """Close all cached connections and clear internal state."""
        keys = list(self._clients.keys())
        close_coros = [
            _close_connection_safely(self._clients.pop(key))
            for key in keys
        ]
        gather_results = await asyncio.gather(
            *close_coros, return_exceptions=True,
        )
        for idx, gather_item in enumerate(gather_results):
            if isinstance(gather_item, Exception):
                logger.warning(
                    "Error closing MCP connection %s: %s",
                    keys[idx], gather_item,
                )
        self._clients.clear()
        for task in self._idle_tasks.values():
            task.cancel()
        self._idle_tasks.clear()
        self._locks.clear()
        logger.info(
            "All MCP connections shut down (%d total)", len(keys),
        )

    async def disconnect(
        self,
        session_id: str,
        skill_name: str,
        mcp_name: str,
    ) -> None:
        """Close and remove a specific connection (idempotent)."""
        conn_key = _client_key(session_id, skill_name, mcp_name)
        task = self._idle_tasks.pop(conn_key, None)
        if task is not None:
            task.cancel()
        conn = self._clients.pop(conn_key, None)
        if conn is None:
            return
        await _close_connection_safely(conn)
        self._locks.pop(conn_key, None)
        logger.debug(
            "MCP connection closed: %s (skill=%s, mcp=%s)",
            session_id, skill_name, mcp_name,
        )

    def _make_key(
        self, session_id: str, skill_name: str, mcp_name: str,
    ) -> str:
        """Build cache key for a (session, skill, mcp) triple."""
        return _client_key(session_id, skill_name, mcp_name)

    def get_connected_servers(self) -> list[str]:
        """Return list of connected server keys."""
        return list(self._clients.keys())

    async def close(self, session_id: str = "") -> None:
        """Close all MCP connections for a session concurrently.

        If ``session_id`` is empty string, closes all connections.
        """
        if session_id:
            prefix = "{}:".format(session_id)
            keys = [
                key for key in self._clients
                if key.startswith(prefix)
            ]
        else:
            keys = list(self._clients.keys())

        close_coros = []
        for key in keys:
            conn = self._clients.pop(key, None)
            if conn is not None:
                close_coros.append(_close_connection_safely(conn))
            self._locks.pop(key, None)
            task = self._idle_tasks.pop(key, None)
            if task is not None:
                task.cancel()

        if close_coros:
            with suppress(asyncio.CancelledError):
                await asyncio.gather(
                    *close_coros, return_exceptions=True,
                )
