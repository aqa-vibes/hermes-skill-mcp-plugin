"""Config parser for hermes-skill-mcp plugin.

Reads skill_dir/mcp.json, SKILL.md frontmatter, or mcp.yaml.
Priority: mcp.json > SKILL.md frontmatter mcp: > mcp.yaml.
Validates, normalizes, returns server configs.
Returns {} if no config found, parse error, or invalid schema.
Never raises exceptions to caller.
"""

# flake8: noqa: WPS202
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants — config keys (extracted to avoid WPS226 string over-use)
# ---------------------------------------------------------------------------

_KEY_TYPE = "type"
_KEY_COMMAND = "command"
_KEY_ARGS = "args"
_KEY_ENV = "env"
_KEY_URL = "url"
_KEY_HEADERS = "headers"
_KEY_TIMEOUT = "timeout"
_KEY_CONNECT_TIMEOUT = "connect_timeout"
_KEY_IDLE_TIMEOUT = "idle_timeout"
_KEY_CWD = "cwd"

# Valid type values for server transport
_VALID_TYPES = frozenset(("stdio", "http", "sse"))

# Fields recognized in a server entry. Unknown fields silently ignored.
KNOWN_FIELDS: frozenset[str] = frozenset((
    _KEY_TYPE,
    _KEY_COMMAND,
    _KEY_ARGS,
    _KEY_ENV,
    _KEY_URL,
    _KEY_HEADERS,
    _KEY_TIMEOUT,
    _KEY_CONNECT_TIMEOUT,
    _KEY_IDLE_TIMEOUT,
    _KEY_CWD,
))

# Default timeout values (seconds)
DEFAULT_TIMEOUT = 60
DEFAULT_CONNECT_TIMEOUT = 10
DEFAULT_IDLE_TIMEOUT = 300

# Max servers per config file
MAX_SERVERS = 32

# Pattern for ${VAR} environment variable references
_ENV_VAR_PATTERN = re.compile(r"\$\{(\w+)\}")

# Frontmatter delimiter
_FRONTMATTER_DELIM = "---"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def check_mcp_sdk_available() -> bool:
    """Return True if ``import mcp`` succeeds, False otherwise.

    Used as ``check_fn`` for the ``skill-mcp`` toolset in Hermes.
    Result is NOT cached — each call re-checks the import.
    """
    try:
        import mcp  # noqa: F401
    except ImportError:
        return False
    return True


def parse_mcp_config(skill_dir: Path) -> dict[str, dict[str, Any]]:
    """Read config from skill_dir, validate, normalize, return server configs.

    Priority order:
    1. ``mcp.json`` (Claude Code compatible, JSON)
    2. ``SKILL.md`` YAML frontmatter ``mcp:`` key
    3. ``mcp.yaml`` (legacy YAML)

    Args:
        skill_dir: Path to skill directory.

    Returns:
        ``{server_name: server_config}``. Returns ``{}`` if no config
        exists, cannot be parsed, or contains no valid entries.
        Never raises an exception.
    """
    # 1. mcp.json (highest priority)
    json_path = skill_dir / "mcp.json"
    if json_path.is_file():
        raw_config = _load_mcp_json(json_path, skill_dir)
        if raw_config is not None:
            return _process_servers(raw_config, json_path, skill_dir)
        # Parse failed → return {} (don't fall through to yaml)
        return {}

    # 2. SKILL.md frontmatter mcp: key
    skill_md_path = skill_dir / "SKILL.md"
    if skill_md_path.is_file():
        raw_config = _load_frontmatter_mcp(skill_md_path, skill_dir)
        if raw_config is not None:
            return _process_servers(raw_config, skill_md_path, skill_dir)

    # 3. mcp.yaml (legacy, lowest priority)
    yaml_path = skill_dir / "mcp.yaml"
    if yaml_path.is_file():
        raw_config = _load_raw_config(yaml_path, skill_dir)
        if raw_config is not None:
            return _process_servers(raw_config, yaml_path, skill_dir)

    return {}


# ---------------------------------------------------------------------------
# Internal helpers — config loading (mcp.json)
# ---------------------------------------------------------------------------


def _load_mcp_json(
    json_path: Path, skill_dir: Path,
) -> dict[str, Any] | None:
    """Parse mcp.json and return raw server dict, or None on failure.

    Accepts two formats:
    - Wrapper: ``{"mcpServers": {...}}`` (Claude Code format)
    - Flat: ``{"server-name": {...}}`` (auto-detected by presence of
      ``command`` or ``url`` in values)
    """
    try:
        raw_text = json_path.read_text(encoding="utf-8")
        _detect_duplicate_json_keys(raw_text, json_path)
        parsed = json.loads(raw_text)
    except Exception as exc:
        logger.warning(
            "skill-mcp: failed to parse mcp.json in %s: %s",
            skill_dir,
            exc,
        )
        return None

    if not isinstance(parsed, dict):
        logger.warning(
            "skill-mcp: mcp.json in %s is not a dict — skipped",
            skill_dir,
        )
        return None

    # Format A: {"mcpServers": {...}} wrapper
    if "mcpServers" in parsed:
        servers = parsed["mcpServers"]
        if not isinstance(servers, dict):
            logger.warning(
                "skill-mcp: mcpServers in %s is not a dict — skipped",
                json_path,
            )
            return None
        return servers  # type: ignore[return-value]

    # Format B: flat auto-detect — values must be dicts with command or url
    has_server_like = any(
        isinstance(val, dict) and (
            _KEY_COMMAND in val or _KEY_URL in val
        )
        for val in parsed.values()
    )
    if has_server_like:
        return parsed  # type: ignore[return-value]

    # No mcpServers key and no server-like entries
    logger.warning(
        "skill-mcp: mcp.json in %s has no mcpServers key"
        " and no entries with command/url — skipped",
        json_path,
    )
    return None


def _detect_duplicate_json_keys(
    raw_text: str, json_path: Path,
) -> None:
    """Scan raw JSON text for duplicate keys, log warnings.

    Python's json.loads silently overwrites duplicate keys.
    This function detects them via object_pairs_hook.
    """
    seen_keys: set[str] = set()

    def _detect_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in seen_keys:
                logger.warning(
                    "skill-mcp: duplicate key '%s' in %s",
                    key,
                    json_path,
                )
            seen_keys.add(key)
            result[key] = value
        return result

    try:
        import json as _json
        _json.loads(raw_text, object_pairs_hook=_detect_pairs)
    except Exception:  # noqa: WPS440
        pass

# ---------------------------------------------------------------------------
# Internal helpers — config loading (SKILL.md frontmatter)
# ---------------------------------------------------------------------------


def _load_frontmatter_mcp(
    skill_md_path: Path, skill_dir: Path,
) -> dict[str, Any] | None:
    """Parse mcp: key from SKILL.md YAML frontmatter.

    Frontmatter must be at the start of the file:
    ---\\n
    name: ...\\n
    mcp:\\n
      server: ...\\n
    ---\\n

    Returns the mcp dict if present, or None if not found.
    Returns None (no error) if no frontmatter or no mcp: key.
    Returns None + warning if YAML is malformed or mcp value is not dict.
    """
    try:
        raw_text = skill_md_path.read_text(encoding="utf-8")
    except Exception as exc:
        logger.warning(
            "skill-mcp: failed to read SKILL.md in %s: %s",
            skill_dir,
            exc,
        )
        return None

    # Frontmatter must start with --- on the first line
    if not raw_text.startswith(_FRONTMATTER_DELIM):
        return None

    # Find the closing ---
    lines = raw_text.splitlines(keepends=True)
    if not lines:
        return None

    # First line should be ---
    first_line = lines[0].strip()
    if first_line != _FRONTMATTER_DELIM:
        return None

    # Find closing ---
    fm_lines: list[str] = []
    closing_found = False
    for idx, line in enumerate(lines[1:], start=1):
        if line.strip() == _FRONTMATTER_DELIM:
            closing_found = True
            break
        fm_lines.append(line)

    if not closing_found:
        return None

    fm_text = "".join(fm_lines)

    # Parse YAML frontmatter
    try:
        import yaml
        fm_data = yaml.safe_load(fm_text)
    except Exception as exc:
        logger.warning(
            "skill-mcp: failed to parse frontmatter in %s: %s",
            skill_md_path,
            exc,
        )
        return None

    if fm_data is None or not isinstance(fm_data, dict):
        return None

    # Extract mcp: key
    if "mcp" not in fm_data:
        return None

    mcp_value = fm_data["mcp"]
    if not isinstance(mcp_value, dict):
        logger.warning(
            "skill-mcp: 'mcp' key in frontmatter of %s"
            " is not a dict — skipped",
            skill_md_path,
        )
        return None

    return mcp_value  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Internal helpers — config loading (mcp.yaml, legacy)
# ---------------------------------------------------------------------------


def _load_raw_config(
    config_path: Path, skill_dir: Path,
) -> dict[str, Any] | None:
    """Parse mcp.yaml and return raw dict, or None on failure."""
    try:  # noqa: WPS229
        import yaml
        raw_text = config_path.read_text(encoding="utf-8")
        _detect_duplicate_keys(raw_text, config_path)
        raw_data = yaml.safe_load(raw_text)
    except Exception as exc:
        logger.warning(
            "skill-mcp: failed to parse mcp.yaml in %s: %s",
            skill_dir,
            exc,
        )
        return None

    if raw_data is None or not isinstance(raw_data, dict):
        return None

    return raw_data  # type: ignore[return-value]


def _detect_duplicate_keys(
    raw_text: str, config_path: Path,
) -> None:
    """Scan raw YAML text for duplicate top-level keys, log warnings.

    PyYAML silently overwrites duplicate keys. This function detects
    them before parsing so we can warn the user.
    """
    seen: set[str] = set()
    for line in raw_text.splitlines():
        stripped = line.strip()
        # Skip empty lines, comments, and indented (nested) lines
        if not stripped or stripped.startswith("#"):
            continue
        if line[0] in (" ", "\t"):
            continue
        # Extract key before first colon on top-level lines
        colon_idx = stripped.find(":")
        if colon_idx == -1:
            continue
        key = stripped[:colon_idx].strip()
        if not key:
            continue
        if key in seen:
            logger.warning(
                "skill-mcp: duplicate server name '%s' in %s",
                key,
                config_path,
            )
        else:
            seen.add(key)


# ---------------------------------------------------------------------------
# Internal helpers — server processing
# ---------------------------------------------------------------------------


def _is_valid_entry_type(
    server_name: object,
    entry: object,
    config_path: Path,
) -> bool:
    """Check server name is str and entry is dict. Log on failure."""
    if not isinstance(server_name, str):
        logger.warning(
            "skill-mcp: non-string server name %r in %s — skipped",
            server_name,
            config_path,
        )
        return False
    if not isinstance(entry, dict):
        logger.warning(
            "skill-mcp: server entry for %r in %s"
            " is not a dict — skipped",
            server_name,
            config_path,
        )
        return False
    return True


def _process_servers(
    raw_config: dict[str, Any],
    config_path: Path,
    skill_dir: Path,
) -> dict[str, dict[str, Any]]:
    """Process all server entries from raw config.

    Validates each entry, enforces max server limit (32),
    checks command/url exclusivity, resolves paths, and
    expands env vars.
    """
    processed: dict[str, dict[str, Any]] = {}
    for server_name, entry in raw_config.items():
        if not _is_valid_entry_type(server_name, entry, config_path):
            continue

        if len(processed) >= MAX_SERVERS:
            logger.warning(
                "skill-mcp: too many MCP servers (%d), max %d."
                " Truncated.",
                len(raw_config),
                MAX_SERVERS,
            )
            break

        server_result = _normalize_server_entry(
            entry, server_name, config_path, skill_dir,
        )
        if server_result is not None:
            processed[server_name] = server_result

    return processed


def _normalize_server_entry(
    entry: dict[str, Any],
    server_name: str,
    config_path: Path,
    skill_dir: Path,
) -> dict[str, Any] | None:
    """Validate and normalize a single server entry.

    Checks type/command/url consistency (including SSE rules),
    builds normalized config with defaults, and validates path
    containment. Returns normalized dict or None if entry is invalid.
    """
    # Validate type field if present
    entry_type = entry.get(_KEY_TYPE)
    if entry_type is not None and entry_type not in _VALID_TYPES:
        logger.warning(
            "skill-mcp: server '%s' in %s has invalid type '%s'"
            " (must be stdio, http, or sse) — skipped",
            server_name,
            config_path,
            entry_type,
        )
        return None

    has_command = _KEY_COMMAND in entry
    has_url = _KEY_URL in entry

    # SSE-specific validation
    if entry_type == "sse":
        if has_command:
            logger.warning(
                "skill-mcp: server '%s' in %s has type 'sse'"
                " but includes command — skipped",
                server_name,
                config_path,
            )
            return None
        if not has_url:
            logger.warning(
                "skill-mcp: server '%s' in %s has type 'sse'"
                " but no url — skipped",
                server_name,
                config_path,
            )
            return None
    elif entry_type == "http":
        if has_command:
            logger.warning(
                "skill-mcp: server '%s' in %s has type 'http'"
                " but includes command — skipped",
                server_name,
                config_path,
            )
            return None
        if not has_url:
            logger.warning(
                "skill-mcp: server '%s' in %s has type 'http'"
                " but no url — skipped",
                server_name,
                config_path,
            )
            return None
    elif entry_type == "stdio":
        if has_url:
            logger.warning(
                "skill-mcp: server '%s' in %s has type 'stdio'"
                " but includes url — skipped",
                server_name,
                config_path,
            )
            return None
        if not has_command:
            logger.warning(
                "skill-mcp: server '%s' in %s has type 'stdio'"
                " but no command — skipped",
                server_name,
                config_path,
            )
            return None
    else:
        # No explicit type — infer from command/url presence
        if has_command == has_url:
            logger.warning(
                "skill-mcp: server '%s' in %s must have exactly"
                " one of '%s' or '%s' — skipped",
                server_name,
                config_path,
                _KEY_COMMAND,
                _KEY_URL,
            )
            return None

    normalized, resolved_paths = _build_normalized_entry(
        entry, config_path, skill_dir,
    )

    if not _validate_paths(
        resolved_paths, skill_dir, server_name, config_path,
    ):
        return None

    return normalized


# ---------------------------------------------------------------------------
# Internal helpers — entry building
# ---------------------------------------------------------------------------


def _build_normalized_entry(
    entry: dict[str, Any],
    config_path: Path,
    skill_dir: Path,
) -> tuple[dict[str, Any], set[Path]]:
    """Build a normalized server entry from raw dict.

    Filters to known fields, fills defaults, expands env vars,
    resolves relative paths (including cwd). Returns
    (normalized_entry, resolved_paths).
    """
    normalized: dict[str, Any] = {
        field: entry[field]
        for field in KNOWN_FIELDS
        if field in entry
    }

    normalized.setdefault(_KEY_ARGS, [])
    normalized.setdefault(_KEY_ENV, {})
    normalized.setdefault(_KEY_HEADERS, {})
    normalized.setdefault(_KEY_TIMEOUT, DEFAULT_TIMEOUT)
    normalized.setdefault(_KEY_CONNECT_TIMEOUT, DEFAULT_CONNECT_TIMEOUT)
    normalized.setdefault(_KEY_IDLE_TIMEOUT, DEFAULT_IDLE_TIMEOUT)

    normalized = _expand_env_vars(normalized)
    normalized, resolved = _resolve_relative_paths(
        normalized, config_path.parent,
    )
    return normalized, resolved


# ---------------------------------------------------------------------------
# Internal helpers — env var expansion
# ---------------------------------------------------------------------------


def _env_var_replacer(match: re.Match[str]) -> str:
    """Replace ${VAR} with value from os.environ, or leave unchanged."""
    var_name = match.group(1)
    return os.environ.get(var_name, match.group(0))


def _expand_env_vars(config_value: Any) -> Any:
    """Recursively expand ``${VAR}`` references in strings using env vars."""
    if isinstance(config_value, str):
        return _ENV_VAR_PATTERN.sub(_env_var_replacer, config_value)
    if isinstance(config_value, dict):
        return {
            key: _expand_env_vars(cfg_val)
            for key, cfg_val in config_value.items()
        }
    if isinstance(config_value, list):
        return [_expand_env_vars(elem) for elem in config_value]
    return config_value


# ---------------------------------------------------------------------------
# Internal helpers — path resolution
# ---------------------------------------------------------------------------


def _resolve_relative_paths(
    config: dict[str, Any],
    base_dir: Path,
) -> tuple[dict[str, Any], set[Path]]:
    """Resolve relative paths in command, args, and cwd to absolute paths."""
    resolved_paths: set[Path] = set()
    config = _resolve_command(config, base_dir, resolved_paths)
    config = _resolve_args(config, base_dir, resolved_paths)
    config = _resolve_cwd(config, base_dir, resolved_paths)
    return config, resolved_paths


def _resolve_command(
    config: dict[str, Any],
    base_dir: Path,
    resolved_paths: set[Path],
) -> dict[str, Any]:
    """Resolve command field if it looks like a relative path."""
    if _KEY_COMMAND not in config:
        return config
    command = config[_KEY_COMMAND]
    if _is_relative_path(command):
        abs_cmd = (base_dir / command).resolve()
        config[_KEY_COMMAND] = str(abs_cmd)
        resolved_paths.add(abs_cmd)
    return config


def _resolve_args(
    config: dict[str, Any],
    base_dir: Path,
    resolved_paths: set[Path],
) -> dict[str, Any]:
    """Resolve args entries that look like relative paths."""
    if _KEY_ARGS not in config:
        return config
    resolved_args: list[str] = []
    for arg in config[_KEY_ARGS]:
        if _is_relative_path(arg):
            abs_arg = (base_dir / arg).resolve()
            resolved_args.append(str(abs_arg))
            resolved_paths.add(abs_arg)
        else:
            resolved_args.append(arg)
    config[_KEY_ARGS] = resolved_args
    return config


def _resolve_cwd(
    config: dict[str, Any],
    base_dir: Path,
    resolved_paths: set[Path],
) -> dict[str, Any]:
    """Resolve cwd field if it looks like a relative path."""
    if _KEY_CWD not in config:
        return config
    cwd_val = config[_KEY_CWD]
    if not isinstance(cwd_val, str):
        return config
    if _is_relative_path(cwd_val) or cwd_val == ".":
        abs_cwd = (base_dir / cwd_val).resolve()
        config[_KEY_CWD] = str(abs_cwd)
        resolved_paths.add(abs_cwd)
    return config


# ---------------------------------------------------------------------------
# Internal helpers — validation
# ---------------------------------------------------------------------------


def _validate_paths(
    resolved_paths: set[Path],
    skill_dir: Path,
    server_name: str,
    config_path: Path,
) -> bool:
    """Check that resolved relative paths do not escape skill directory.

    Only paths that were resolved from relative entries are checked.
    Absolute paths (e.g. /data/db.sqlite) are trusted as explicit
    user intent and are NOT escape-checked.
    """
    skill_root = skill_dir.resolve()
    for path in resolved_paths:
        try:
            path.relative_to(skill_root)
        except ValueError:
            logger.warning(
                "skill-mcp: path '%s' escapes skill directory"
                " for server '%s' in %s — entry rejected",
                path,
                server_name,
                config_path,
            )
            return False
    return True


def _is_relative_path(candidate: str) -> bool:
    """Return True if candidate looks like a relative filesystem path."""
    if Path(candidate).is_absolute():
        return False
    return "/" in candidate or "\\" in candidate
