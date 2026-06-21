"""
Skill view hook — transform_tool_result hook for skill_view augmentation.

Appends static MCP server config when skill_view is called for a skill
with mcp.yaml. No MCP handshake — static config display only.
"""

# flake8: noqa: WPS202

from __future__ import annotations

import importlib
import json
import logging
from pathlib import Path
from typing import Any, Callable, Optional

import _security
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MASK_THRESHOLD = 8
_DEFAULT_MCP_TIMEOUT = 60
_DEFAULT_MCP_CONNECT_TIMEOUT = 10
_DEFAULT_MCP_IDLE_TIMEOUT = 300

# ---------------------------------------------------------------------------
# Existing helpers — unchanged signatures
# ---------------------------------------------------------------------------


def _get_parse_mcp_config():
    """Import _config module without relative imports."""
    spec = importlib.util.spec_from_file_location(
        "_config",
        Path(__file__).parent / "_config.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.parse_mcp_config


def _format_server_line(name: str, server: dict) -> str:
    """Format a single MCP server entry for display."""
    cmd = server.get("command", "?")
    args_text = " ".join(server.get("args", []))
    return f"- **{name}**: `{cmd} {args_text}`"


def _build_mcp_section(servers: dict) -> str:
    """Build formatted MCP servers section from parsed config."""
    lines = ["## MCP Servers", ""]
    for name, server in servers.items():
        lines.append(_format_server_line(name, server))
    return "\n".join(lines)


def skill_view_extra(skill_dir: Path) -> Optional[str]:
    """Return MCP server info to display in skill view. Called as hook."""
    parse_mcp_config = _get_parse_mcp_config()
    config = parse_mcp_config(skill_dir)
    if not config:
        return None
    return _build_mcp_section(config)


# ---------------------------------------------------------------------------
# transform_tool_result hook factory — from legacy 9cc7c0a
# ---------------------------------------------------------------------------


def create_hook(
    skill_dirs: list[str] | None = None,
) -> Callable[..., str | None]:
    """Return a transform_tool_result hook function.

    Args:
        skill_dirs: Skill directory paths (reserved for future use).
                    Currently unused — the hook reads the path from the
                    skill_view result directly.

    Returns:
        Hook function compatible with Hermes transform_tool_result
        contract.  Returns str to replace result, or None to pass
        through.
    """
    # skill_dirs accepted for API compatibility but unused.

    def hook(**kwargs: Any) -> str | None:  # noqa: WPS430
        try:
            return _transform_hook(kwargs)
        except Exception:
            # Fail-open: exceptions caught, original result preserved.
            logger.debug("skill_view hook error", exc_info=True)
            return None

    return hook


def _transform_hook(kwargs: dict[str, Any]) -> str | None:
    """Gate on tool_name=="skill_view", then augment the result."""
    if kwargs.get("tool_name") != "skill_view":
        return None
    raw_result = kwargs.get("result")
    if not isinstance(raw_result, str):
        return None
    return _augment_skill_view_result(raw_result)


def _augment_skill_view_result(raw_result: str) -> str | None:
    """Parse JSON, validate path, look up mcp.yaml, return augmented."""
    parsed = _safe_parse_json(raw_result)
    if parsed is None:
        return None
    if not _is_valid_skill_path(parsed):
        return None
    return _append_mcp_section(raw_result, Path(parsed["path"]))


def _append_mcp_section(raw_result: str, skill_path: Path) -> str | None:
    """Look up mcp.yaml, format BDD 6.2 section, append to result."""
    parse_mcp_config = _get_parse_mcp_config()
    config = parse_mcp_config(skill_path)
    if not config:
        return None
    mcp_section = _build_hook_mcp_section(config, skill_path.name)
    return raw_result + "\n\n" + mcp_section


def _safe_parse_json(text: str) -> dict | None:
    """Parse JSON string; return None on any failure (passthrough)."""
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def _is_valid_skill_path(parsed: dict) -> bool:
    """Check parsed result has a valid, existing skill directory path."""
    if "path" not in parsed:
        return False
    if parsed.get("ok") is False:
        return False
    skill_path = Path(parsed["path"])
    return skill_path.is_dir()


# ---------------------------------------------------------------------------
# BDD 6.2 MCP section formatting
# ---------------------------------------------------------------------------


def _build_hook_mcp_section(
    config: dict[str, dict[str, Any]], skill_name: str,
) -> str:
    """Build MCP Servers section matching BDD 6.2 output format.

    Format:

        ## MCP Servers

        ### <server_name>

        *Static config — connect on first ``skill_mcp`` call.*

        **Configuration:**
          url: <url>
          or: command: <command> [args]
          timeout: <N>s
          connect_timeout: <N>s
          idle_timeout: <N>s

        Use ``skill_mcp(...)`` to invoke.
    """
    lines: list[str] = ["## MCP Servers", ""]
    for server_name, server_config in config.items():
        _append_server_block(
            lines, server_name, server_config, skill_name,
        )
    return "\n".join(lines)


def _append_server_block(
    lines: list[str],
    name: str,
    server_config: dict[str, Any],
    skill_name: str,
) -> None:
    """Append a single MCP server sub-section to lines list."""
    lines.append(f"### {name}")
    lines.append("")
    lines.append(
        "*Static config — connect on first `skill_mcp` call.*",
    )
    lines.append("")
    lines.append("**Configuration:**")
    _append_command_or_url(lines, server_config)
    _append_timeouts(lines, server_config)
    lines.append("")
    usage = (
        f'Use `skill_mcp(skill_name="{skill_name}", '
        f'mcp_name="{name}", '
        f'tool_name="...", '
        f'arguments={{...}})` to invoke.'
    )
    lines.append(usage)
    lines.append("")


def _append_command_or_url(
    lines: list[str], config: dict[str, Any],
) -> None:
    """Append command or url portion of server configuration."""
    if "url" in config:
        lines.append(f"  url: {config['url']}")
        headers = config.get("headers", {})
        if headers:
            header_str = _format_headers(headers)
            lines.append(f"  headers: {header_str}")
    else:
        command = config.get("command", "")
        args = config.get("args", [])
        if args:
            cmd_line = f"  command: {command} {' '.join(args)}"
            lines.append(cmd_line)
        else:
            lines.append(f"  command: {command}")


def _append_timeouts(
    lines: list[str], config: dict[str, Any],
) -> None:
    """Append timeout lines for a server configuration."""
    lines.append(f"  timeout: {config.get('timeout', _DEFAULT_MCP_TIMEOUT)}s")
    lines.append(
        f"  connect_timeout: {config.get('connect_timeout', _DEFAULT_MCP_CONNECT_TIMEOUT)}s",
    )
    lines.append(
        f"  idle_timeout: {config.get('idle_timeout', _DEFAULT_MCP_IDLE_TIMEOUT)}s",
    )


def _format_headers(headers: dict[str, str]) -> str:
    """Format headers dict for display, redacting credential values.

    Args:
        headers: Header key-value pairs from mcp.yaml.

    Returns:
        Comma-separated string like
        "Authorization: Bearer ***, X-Custom: ***".
    """
    parts: list[str] = []
    for key, header_value in headers.items():
        redacted = _redact_header_value(str(header_value))
        parts.append(f"{key}: {redacted}")
    return ", ".join(parts)


def _redact_header_value(header_value: str) -> str:
    """Redact a single header value by masking credentials.

    Uses _security.redact_credentials if available, otherwise falls
    back to simple masking.
    """
    redacted_from_security = _try_security_redact(header_value)
    if redacted_from_security is not None:
        return redacted_from_security
    return _fallback_mask(header_value)


def _try_security_redact(text: str) -> str | None:
    """Attempt credential redaction via _security module."""
    try:
        redacted = _security.redact_credentials(text)
    except (ImportError, AttributeError):
        return None
    if redacted != text:
        return redacted
    return None


def _fallback_mask(text: str) -> str:
    """Mask long values with '***'."""
    if len(text) > _MASK_THRESHOLD:
        return text[:4] + "***"
    return "***"
