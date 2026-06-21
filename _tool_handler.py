"""Async handler for the skill_mcp tool.

Module Interface
----------------
SKILL_MCP_SCHEMA : dict
    OpenAI function-calling schema for the skill_mcp tool.
create_handler(manager, skill_dirs=None) -> Callable
    Returns async handler compatible with Hermes registry.
    skill_dirs: override skill search paths (default: platform defaults).
Handler: async handler returns standardised JSON result.
    Validates args, resolves skill MCP config, delegates to manager.
"""

# flake8: noqa: WPS202
from __future__ import annotations

import asyncio
import json
import logging
import re as _re
from pathlib import Path as _Path
from typing import Any, Callable

from _config import check_mcp_sdk_available, parse_mcp_config  # noqa: WPS300
from _security import redact_credentials  # noqa: WPS300

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Path/filename
_SKILL_MD_FILENAME = "SKILL.md"

# Numeric
_DEFAULT_TIMEOUT = 60

# Argument keys
_KEY_SKILL_NAME = "skill_name"
_KEY_MCP_NAME = "mcp_name"
_KEY_TOOL_NAME = "tool_name"
_KEY_RESOURCE_NAME = "resource_name"
_KEY_PROMPT_NAME = "prompt_name"
_KEY_ARGUMENTS = "arguments"
_KEY_GREP = "grep"
_KEY_SESSION_ID = "session_id"
_KEY_TIMEOUT = "timeout"
_DEFAULT_SESSION_ID = "default"

# JSON response keys
_JKEY_OK = "ok"
_JKEY_ERROR_CODE = "error_code"
_JKEY_MESSAGE = "message"
_JKEY_RETRYABLE = "retryable"
_JKEY_DATA = "data"

# Message strings
_MSG_SDK_MISSING = "MCP SDK not installed. Run: pip install mcp"
_MSG_NO_OPERATION = "No operation specified."
_MSG_SESSION_MISSING = "No active session available for skill MCP call."

# Schema string constants (avoid WPS226 string over-use)
_S_TYPE = "type"
_S_STRING = "string"
_S_OBJECT = "object"
_S_DESC = "description"
_S_PROPERTIES = "properties"
_S_REQUIRED = "required"

# Error codes
_EC_INVALID_ARGS = "INVALID_ARGS"
_EC_MCP_SDK_MISSING = "MCP_SDK_MISSING"
_EC_SKILL_NOT_FOUND = "SKILL_NOT_FOUND"
_EC_NO_MCP_CONFIG = "NO_MCP_CONFIG"
_EC_MCP_NOT_FOUND = "MCP_NOT_FOUND"
_EC_NO_SESSION = "NO_SESSION"
_EC_MCP_CONNECT_FAILED = "MCP_CONNECT_FAILED"
_EC_MCP_SERVER_EXITED = "MCP_SERVER_EXITED"
_EC_MCP_TOOLS_UNAVAILABLE = "MCP_TOOLS_UNAVAILABLE"
_EC_MCP_UNSUPPORTED_PROTOCOL = "MCP_UNSUPPORTED_PROTOCOL"
_EC_MCP_TOOL_TIMEOUT = "MCP_TOOL_TIMEOUT"
_EC_MCP_TOOL_NOT_FOUND = "MCP_TOOL_NOT_FOUND"
_EC_MCP_TOOL_ERROR = "MCP_TOOL_ERROR"


# ---------------------------------------------------------------------------
# Exception hierarchy (shared interface for SkillMcpManager)
# ---------------------------------------------------------------------------

class McpError(Exception):
    """Base exception for MCP-related errors raised by SkillMcpManager."""


class McpConnectionError(McpError):
    """Connection to MCP server failed (command not found, timeout, etc.)."""


class McpToolNotFoundError(McpError):
    """Requested tool/resource/prompt not found on the MCP server."""


class McpToolExecutionError(McpError):
    """MCP tool execution failed with a runtime error."""


class McpServerExitedError(McpError):
    """MCP server process exited unexpectedly during a call."""


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

SKILL_MCP_SCHEMA: dict = {  # noqa: WPS407
    "name": "skill_mcp",
    _S_DESC: (
        "Invoke MCP server operations from skill-embedded MCPs. "
        "Requires skill_name + mcp_name + exactly one of: "
        "tool_name, resource_name, prompt_name."
    ),
    _S_PROPERTIES: {
        _S_TYPE: _S_OBJECT,
        _S_PROPERTIES: {
            _KEY_SKILL_NAME: {
                _S_TYPE: _S_STRING,
                _S_DESC: "Skill name as returned by skill_view",
            },
            _KEY_MCP_NAME: {
                _S_TYPE: _S_STRING,
                _S_DESC: "MCP server name from skill's mcp.yaml",
            },
            _KEY_TOOL_NAME: {
                _S_TYPE: _S_STRING,
                _S_DESC: "MCP tool to call",
            },
            _KEY_RESOURCE_NAME: {
                _S_TYPE: _S_STRING,
                _S_DESC: "MCP resource URI to read",
            },
            _KEY_PROMPT_NAME: {
                _S_TYPE: _S_STRING,
                _S_DESC: "MCP prompt to get",
            },
            _KEY_ARGUMENTS: {
                _S_TYPE: _S_OBJECT,
                _S_DESC: "Tool/prompt arguments as JSON object",
            },
            _KEY_GREP: {
                _S_TYPE: _S_STRING,
                _S_DESC: "Regex pattern to filter output lines",
            },
        },
        _S_REQUIRED: [_KEY_SKILL_NAME, _KEY_MCP_NAME],
    },
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class _HandlerCallable:
    """Async callable wrapping handler with bound skill dirs."""

    def __init__(
        self,
        manager: Any,
        resolved_dirs: list[_Path],
    ) -> None:
        """Store bound manager and resolved directories."""
        self._manager = manager
        self._resolved_dirs = resolved_dirs

    async def __call__(self, call_args: dict, **kwargs: Any) -> str:
        """Invoke the skill_mcp handler pipeline."""
        return await _handle_skill_mcp(
            call_args, self._manager, self._resolved_dirs, **kwargs,
        )


def create_handler(
    manager: Any,  # SkillMcpManager
    skill_dirs: list[str] | None = None,
) -> Callable[..., Any]:
    """Return async handler for the skill_mcp tool.

    Args:
        manager: SkillMcpManager instance for connection lifecycle.
        skill_dirs: Override skill search paths.
            Default: ``[~/.hermes/skills, ~/.hermes/optional-skills]``.

    Returns:
        Async callable ``handler(args, **kwargs) -> str``.
    """
    resolved: list[_Path] = _resolve_skill_dirs(skill_dirs)
    return _HandlerCallable(manager, resolved)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

async def _handle_skill_mcp(
    call_args: dict,
    manager: Any,
    skill_dirs: list[_Path],
    **kwargs: Any,
) -> str:
    """Core orchestrator: validate → prereqs → resolve → execute → format."""
    err = _validate_args(call_args)
    if err:
        return err

    err = _check_sdk_available()
    if err:
        return err

    outcome = _resolve_skill_config(
        call_args[_KEY_SKILL_NAME],
        call_args[_KEY_MCP_NAME],
        skill_dirs,
    )
    if not outcome[_JKEY_OK]:
        return outcome[_JKEY_ERROR]

    session_id = kwargs.get(_KEY_SESSION_ID, _DEFAULT_SESSION_ID)
    err = _validate_session(session_id)
    if err:
        return err

    outcome = await _get_or_create_client(
        manager,
        session_id,
        call_args[_KEY_SKILL_NAME],
        call_args[_KEY_MCP_NAME],
        outcome["config"],
    )
    if not outcome[_JKEY_OK]:
        return outcome[_JKEY_ERROR]

    outcome = await _execute_operation(
        outcome["client"],
        call_args,
        call_args[_KEY_MCP_NAME],
        outcome["config"],
    )
    if not outcome[_JKEY_OK]:
        return outcome[_JKEY_ERROR]

    return _format_response(outcome[_JKEY_DATA], call_args.get(_KEY_GREP))


# ---------------------------------------------------------------------------
# Pipeline stage: check_prerequisites
# ---------------------------------------------------------------------------

def _check_sdk_available() -> str | None:
    """Return error JSON string if MCP SDK is not installed."""
    if not check_mcp_sdk_available():
        return _build_error(
            _EC_MCP_SDK_MISSING, _MSG_SDK_MISSING, retryable=False,
        )
    return None


# ---------------------------------------------------------------------------
# Pipeline stage: resolve_config
# ---------------------------------------------------------------------------

def _resolve_skill_config(
    skill_name: str,
    mcp_name: str,
    skill_dirs: list[_Path],
) -> dict[str, Any]:
    """Resolve skill directory and MCP config.

    Returns:
        {"ok": True, "config": <dict>} or
        {"ok": False, "error": "<json>"}
    """
    skill_dir = _find_skill_dir(skill_name, skill_dirs)
    if skill_dir is None:
        return {
            _JKEY_OK: False,
            _JKEY_ERROR: _build_error(
                _EC_SKILL_NOT_FOUND,
                f"Skill '{skill_name}' not found in skill directories.",
                retryable=False,
            ),
        }

    configs = parse_mcp_config(skill_dir)
    if not configs:
        return {
            _JKEY_OK: False,
            _JKEY_ERROR: _build_error(
                _EC_NO_MCP_CONFIG,
                f"Skill '{skill_name}' has no MCP servers configured.",
                retryable=False,
            ),
        }

    if mcp_name not in configs:
        available = ", ".join(sorted(configs.keys()))
        return {
            _JKEY_OK: False,
            _JKEY_ERROR: _build_error(
                _EC_MCP_NOT_FOUND,
                f"MCP server '{mcp_name}' not found in skill "
                f"'{skill_name}'. Available: {available}",
                retryable=False,
            ),
        }

    return {_JKEY_OK: True, "config": configs[mcp_name]}


def _validate_session(session_id: str) -> str | None:
    """Return error JSON if session_id is falsy."""
    if not session_id:
        return _build_error(
            _EC_NO_SESSION, _MSG_SESSION_MISSING, retryable=False,
        )
    return None


# ---------------------------------------------------------------------------
# Pipeline stage: execute_operation (get client + dispatch + timeout)
# ---------------------------------------------------------------------------

async def _get_or_create_client(
    manager: Any,
    session_id: str,
    skill_name: str,
    mcp_name: str,
    config: dict[str, Any],
) -> dict[str, Any]:
    """Get or create MCP client session.

    Returns:
        {"ok": True, "client": <Any>} or
        {"ok": False, "error": "<json>"}
    """
    try:
        client = await manager.get_or_create_client(
            session_id, skill_name, mcp_name, config,
        )
        return {_JKEY_OK: True, "client": client}
    except McpConnectionError as exc:
        return _client_err(
            _EC_MCP_CONNECT_FAILED, exc, retryable=True,
        )
    except McpServerExitedError as exc:
        return _client_err(
            _EC_MCP_SERVER_EXITED, exc, retryable=True,
        )
    except RuntimeError as exc:
        error_code, retryable = _classify_runtime_error(str(exc))
        return _client_err(error_code, exc, retryable=retryable)


def _classify_runtime_error(message: str) -> tuple[str, bool]:
    """Map RuntimeError message to specific error code."""
    lower = message.lower()
    if "not support tools" in lower or "capabilit" in lower:
        return (_EC_MCP_TOOLS_UNAVAILABLE, False)
    if "protocol" in lower or "version" in lower:
        return (_EC_MCP_UNSUPPORTED_PROTOCOL, False)
    return (_EC_MCP_CONNECT_FAILED, True)


def _client_err(
    error_code: str,
    exc: BaseException,
    *,
    retryable: bool,
) -> dict[str, Any]:
    """Build a client error outcome dict with redacted message."""
    return {
        _JKEY_OK: False,
        _JKEY_ERROR: _build_error(
            error_code, redact_credentials(str(exc)), retryable=retryable,
        ),
    }


async def _execute_operation(
    client: Any,
    call_args: dict[str, Any],
    mcp_name: str,
    config: dict[str, Any],
) -> dict[str, Any]:
    """Execute MCP operation with timeout.

    Returns:
        {"ok": True, "data": "<content>"} or
        {"ok": False, "error": "<json>"}
    """
    tool_name = call_args.get(_KEY_TOOL_NAME)
    resource_name = call_args.get(_KEY_RESOURCE_NAME)
    prompt_name = call_args.get(_KEY_PROMPT_NAME)
    call_arguments = call_args.get(_KEY_ARGUMENTS, {})
    timeout = config.get(_KEY_TIMEOUT, _DEFAULT_TIMEOUT)

    if not any([tool_name, resource_name, prompt_name]):
        return {
            _JKEY_OK: False,
            _JKEY_ERROR: _build_error(
                _EC_INVALID_ARGS, _MSG_NO_OPERATION, retryable=False,
            ),
        }

    try:
        mcp_result = await _call_mcp_operation(
            client, tool_name, resource_name,
            prompt_name, call_arguments, timeout,
        )
        return {
            _JKEY_OK: True,
            _JKEY_DATA: _extract_content(mcp_result),
        }
    except asyncio.TimeoutError:
        return {
            _JKEY_OK: False,
            _JKEY_ERROR: _build_error(
                _EC_MCP_TOOL_TIMEOUT,
                f"Tool call timed out after {timeout}s "
                f"on MCP server '{mcp_name}'.",
                retryable=True,
            ),
        }
    except McpToolNotFoundError as exc:
        return _client_err(
            _EC_MCP_TOOL_NOT_FOUND, exc, retryable=False,
        )
    except McpToolExecutionError as exc:
        return _client_err(
            _EC_MCP_TOOL_ERROR, exc, retryable=False,
        )
    except McpServerExitedError as exc:
        return _client_err(
            _EC_MCP_SERVER_EXITED, exc, retryable=True,
        )


async def _call_mcp_operation(
    client: Any,
    tool_name: str | None,
    resource_name: str | None,
    prompt_name: str | None,
    call_arguments: dict[str, Any],
    timeout: int,
) -> Any:
    """Dispatch to correct MCP operation with ``asyncio.wait_for``."""
    if tool_name:
        return await asyncio.wait_for(
            client.call_tool(name=tool_name, arguments=call_arguments),
            timeout=timeout,
        )
    if resource_name:
        return await asyncio.wait_for(
            client.read_resource(uri=resource_name),
            timeout=timeout,
        )
    return await asyncio.wait_for(
        client.get_prompt(name=prompt_name, arguments=call_arguments),
        timeout=timeout,
    )


# ---------------------------------------------------------------------------
# Pipeline stage: format_response
# ---------------------------------------------------------------------------

def _format_response(content_text: str, grep_pattern: str | None) -> str:
    """Apply grep filter and format success JSON response."""
    if grep_pattern and content_text:
        content_text = _apply_grep(content_text, grep_pattern)
    return json.dumps({_JKEY_OK: True, _JKEY_DATA: content_text})


def _apply_grep(text: str, pattern: str) -> str:
    """Filter text lines matching regex. Returns raw text on regex error."""
    try:
        regex = _re.compile(pattern)
        return "\n".join(
            line for line in text.split("\n") if regex.search(line)
        )
    except _re.error:
        return text


# ---------------------------------------------------------------------------
# Argument validation
# ---------------------------------------------------------------------------

def _validate_args(call_args: dict) -> str | None:
    """Validate handler arguments. Returns error JSON string or None."""
    skill_name = call_args.get(_KEY_SKILL_NAME, "")
    if not isinstance(skill_name, str) or not skill_name:
        return _build_error(
            _EC_INVALID_ARGS, "skill_name is required.", retryable=False,
        )

    mcp_name = call_args.get(_KEY_MCP_NAME, "")
    if not isinstance(mcp_name, str) or not mcp_name:
        return _build_error(
            _EC_INVALID_ARGS, "mcp_name is required.", retryable=False,
        )

    tool_name = call_args.get(_KEY_TOOL_NAME)
    resource_name = call_args.get(_KEY_RESOURCE_NAME)
    prompt_name = call_args.get(_KEY_PROMPT_NAME)

    provided = [
        name for name in (tool_name, resource_name, prompt_name) if name
    ]
    if len(provided) == 0:
        return _build_error(
            _EC_INVALID_ARGS,
            "At least one of tool_name, resource_name, or "
            "prompt_name is required.",
            retryable=False,
        )

    if len(provided) > 1:
        return _build_error(
            _EC_INVALID_ARGS,
            "Exactly one of tool_name, resource_name, or "
            "prompt_name is required.",
            retryable=False,
        )

    return None


# ---------------------------------------------------------------------------
# Skill directory lookup
# ---------------------------------------------------------------------------

def _find_skill_dir(
    skill_name: str,
    skill_dirs: list[_Path],
) -> _Path | None:
    """Search skill_dirs for dir named *skill_name* containing SKILL.md."""
    for dir_path in skill_dirs:
        candidate = dir_path / skill_name
        if candidate.is_dir() and (
            candidate / _SKILL_MD_FILENAME
        ).is_file():
            return candidate
    return None


# ---------------------------------------------------------------------------
# Response formatting
# ---------------------------------------------------------------------------

def _build_error(error_code: str, message: str, *, retryable: bool) -> str:
    """Build a standardised error response JSON string."""
    return json.dumps(
        {
            _JKEY_OK: False,
            _JKEY_ERROR_CODE: error_code,
            _JKEY_MESSAGE: message,
            _JKEY_RETRYABLE: retryable,
        },
    )


# ---------------------------------------------------------------------------
# Content extraction
# ---------------------------------------------------------------------------

def _extract_content(mcp_result: Any) -> str:
    """Extract text content from MCP result.

    Handles ``CallToolResult``, ``ReadResourceResult``,
    ``GetPromptResult``, and plain strings.
    """
    if mcp_result is None:
        return ""
    if isinstance(mcp_result, str):
        return mcp_result
    if hasattr(mcp_result, "content"):
        return _extract_content_items(mcp_result.content)
    if hasattr(mcp_result, "messages"):
        return str(mcp_result.messages)
    return str(mcp_result)


def _extract_content_items(items: Any) -> str:
    """Extract text from a list of MCP content items."""
    parts: list[str] = []
    for content_item in items:
        if isinstance(content_item, str):
            parts.append(content_item)
        elif hasattr(content_item, "text"):
            parts.append(content_item.text)
        elif hasattr(content_item, "data"):
            parts.append(str(content_item.data))
    return "\n".join(parts) if parts else str(items)


# ---------------------------------------------------------------------------
# Skill directory resolution
# ---------------------------------------------------------------------------

def _resolve_skill_dirs(skill_dirs: list[str] | None) -> list[_Path]:
    """Return resolved list of skill directories."""
    if skill_dirs is not None:
        return [
            _Path(dir_path).expanduser().resolve() for dir_path in skill_dirs
        ]
    home = _Path.home()
    return [
        home / ".hermes" / "skills",
        home / ".hermes" / "optional-skills",
    ]
