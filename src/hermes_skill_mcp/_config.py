"""mcp.yaml config parser for hermes-skill-mcp plugin.

Reads skill_dir/mcp.yaml, validates, normalizes, returns server
configs. Returns {} if no mcp.yaml, parse error, or invalid schema.
Never raises exceptions to caller.
"""

# flake8: noqa: WPS202
from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants — config keys (extracted to avoid WPS226 string over-use)
# ---------------------------------------------------------------------------

_KEY_COMMAND = "command"
_KEY_ARGS = "args"
_KEY_ENV = "env"
_KEY_URL = "url"
_KEY_HEADERS = "headers"
_KEY_TIMEOUT = "timeout"
_KEY_CONNECT_TIMEOUT = "connect_timeout"
_KEY_IDLE_TIMEOUT = "idle_timeout"

# Fields recognized in a server entry. Unknown fields silently ignored.
KNOWN_FIELDS: frozenset[str] = frozenset((
    _KEY_COMMAND,
    _KEY_ARGS,
    _KEY_ENV,
    _KEY_URL,
    _KEY_HEADERS,
    _KEY_TIMEOUT,
    _KEY_CONNECT_TIMEOUT,
    _KEY_IDLE_TIMEOUT,
))

# Default timeout values (seconds)
DEFAULT_TIMEOUT = 60
DEFAULT_CONNECT_TIMEOUT = 10
DEFAULT_IDLE_TIMEOUT = 300

# Max servers per mcp.yaml
MAX_SERVERS = 32

# Pattern for ${VAR} environment variable references
_ENV_VAR_PATTERN = re.compile(r"\$\{(\w+)\}")


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
    """Read *skill_dir*/mcp.yaml, validate, normalize, return server configs.

    Args:
        skill_dir: Path to skill directory that MAY contain ``mcp.yaml``.

    Returns:
        ``{server_name: server_config}``. Returns ``{}`` if ``mcp.yaml``
        does not exist, cannot be parsed, or contains no valid entries.
        Never raises an exception.
    """
    config_path = skill_dir / "mcp.yaml"
    if not config_path.is_file():
        return {}

    raw_config = _load_raw_config(config_path, skill_dir)
    if raw_config is None:
        return {}

    return _process_servers(raw_config, config_path, skill_dir)


# ---------------------------------------------------------------------------
# Internal helpers — config loading
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
    """Process all server entries from raw YAML config.

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

    Checks command/url exclusivity, builds normalized config
    with defaults, and validates path containment.
    Returns normalized dict or None if entry is invalid.
    """
    has_command = _KEY_COMMAND in entry
    has_url = _KEY_URL in entry
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
    """Build a normalized server entry from raw YAML dict.

    Filters to known fields, fills defaults, expands env vars,
    resolves relative paths. Returns (normalized_entry, resolved_paths).
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
    """Resolve relative paths in command and args to absolute paths."""
    resolved_paths: set[Path] = set()
    config = _resolve_command(config, base_dir, resolved_paths)
    config = _resolve_args(config, base_dir, resolved_paths)
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
