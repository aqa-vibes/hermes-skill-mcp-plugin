"""
Skill view hook — shows MCP servers in skill display.
"""
import importlib
from pathlib import Path
from typing import Optional


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
