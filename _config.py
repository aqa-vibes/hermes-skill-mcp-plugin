"""
MCP configuration parser for skill mcp.yaml files.

Parses mcp.yaml in skill directories. Format same as Hermes
top-level mcp_servers config:

  time:
    command: uvx
    args: ["mcp-server-time"]
    timeout: 30
"""
import yaml
from pathlib import Path
from typing import Optional


def parse_mcp_config(skill_dir: Path) -> Optional[dict]:
    """Parse mcp.yaml from skill directory. Returns None if not found."""
    config_path = skill_dir / "mcp.yaml"
    if not config_path.exists():
        return None

    with open(config_path) as config_file:
        config = yaml.safe_load(config_file)

    if not config or not isinstance(config, dict):
        return None

    return config
