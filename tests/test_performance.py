# flake8: noqa: WPS202,WPS204,WPS226
# pyright: reportArgumentType=false
"""Performance tests for hermes-skill-mcp plugin.

Tests parse latency and cached connection lookup overhead.
All tests marked @pytest.mark.slow.
"""
from __future__ import annotations

import asyncio
import time
from unittest.mock import MagicMock

import pytest

from conftest import import_plugin_module
from hermes_skill_mcp._connection import SkillMcpManager, _client_key

parse_mcp_config = import_plugin_module("_config").parse_mcp_config


@pytest.mark.slow
class TestParseLatency:
    """parse_mcp_config latency benchmarks."""

    def test_parse_latency_under_50ms(self, skill_with_mcp):
        """Parse 3-server mcp.yaml, assert elapsed < 50ms."""
        mcp_config = {
            "sqlite": {
                "command": "uvx",
                "args": ["mcp-server-sqlite"],
            },
            "github": {
                "command": "npx",
                "args": [
                    "-y", "@modelcontextprotocol/server-github",
                ],
            },
            "filesystem": {
                "command": "npx",
                "args": [
                    "-y",
                    "@modelcontextprotocol/server-filesystem",
                    "/tmp",
                ],
            },
        }
        skill_dir = skill_with_mcp("perf-parse", mcp_config)

        start = time.perf_counter()
        result = parse_mcp_config(skill_dir)
        elapsed = (time.perf_counter() - start) * 1000

        assert len(result) == 3
        assert "sqlite" in result
        assert "github" in result
        assert "filesystem" in result
        assert elapsed < 50, (
            "Parse took {:.2f}ms, expected < 50ms".format(elapsed)
        )

    def test_empty_config_parse_latency(self, tmp_path):
        """Parse nonexistent dir, assert returns {}, elapsed < 10ms."""
        nonexistent = tmp_path / "no-such-dir"

        start = time.perf_counter()
        result = parse_mcp_config(nonexistent)
        elapsed = (time.perf_counter() - start) * 1000

        assert result == {}
        assert elapsed < 10, (
            "Parse took {:.2f}ms, expected < 10ms".format(elapsed)
        )


@pytest.mark.slow
class TestCachedLookup:
    """Cached client lookup performance."""

    def test_cached_overhead_under_50ms(self):
        """Pre-populate cache, assert get_or_create_client < 50ms."""
        manager = SkillMcpManager()
        key = _client_key("s1", "skill_a", "time")

        fake_conn = MagicMock()
        fake_conn.session = MagicMock()
        manager._clients[key] = fake_conn

        async def _get():
            return await manager.get_or_create_client(
                "s1", "skill_a", "time", {},
            )

        start = time.perf_counter()
        session = asyncio.run(_get())
        elapsed = (time.perf_counter() - start) * 1000

        assert session is fake_conn.session
        assert elapsed < 50, (
            "Cached lookup took {:.2f}ms, expected < 50ms".format(elapsed)
        )
