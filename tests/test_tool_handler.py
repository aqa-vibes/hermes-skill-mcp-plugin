# TODO: fix wemake WPS202,WPS204,WPS235,WPS402,WPS226 — test module: many test cases, repeated assertions, pattern overuse
# flake8: noqa: WPS202,WPS204,WPS235,WPS402,WPS226 — test module patterns
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from _tool_handler import (
    SKILL_MCP_SCHEMA,
)
from _tool_handler import (
    McpConnectionError,
    McpServerExitedError,
    McpToolExecutionError,
    McpToolNotFoundError,
    _build_error,
    _extract_content,
    _find_skill_dir,
    _resolve_skill_dirs,
    _validate_args,
    create_handler,
)


# ============================================================================
# FakeSkillMcpManager — mock with SkillMcpManager interface
# ============================================================================


class FakeSkillMcpManager:
    def __init__(self):
        self._clients: dict[tuple, MagicMock] = {}
        self.get_or_create_client_calls: list[tuple] = []
        self._connect_error: Exception | None = None

    def configure_error(self, exc: Exception) -> None:
        self._connect_error = exc

    async def get_or_create_client(
        self,
        session_id: str,
        skill_name: str,
        mcp_name: str,
        config: dict,
    ):
        self.get_or_create_client_calls.append(
            (session_id, skill_name, mcp_name, config)
        )
        if self._connect_error:
            raise self._connect_error
        key = (session_id, skill_name, mcp_name)
        if key not in self._clients:
            client = MagicMock()
            client.call_tool = AsyncMock()
            client.read_resource = AsyncMock()
            client.get_prompt = AsyncMock()
            self._clients[key] = client
        return self._clients[key]

    async def disconnect(
        self,
        session_id: str,
        skill_name: str,
        mcp_name: str,
    ) -> None:
        key = (session_id, skill_name, mcp_name)
        self._clients.pop(key, None)

    async def shutdown_all(self) -> None:
        self._clients.clear()

    def get_connected_servers(self) -> list[str]:
        return [
            f"{sess}:{skill}:{mcp_name_suffix}"
            for (sess, skill, mcp_name_suffix) in self._clients
        ]


# ============================================================================
# SKILL_MCP_SCHEMA tests
# ============================================================================


class TestSkillMcpSchema:
    def test_schema_name_is_skill_mcp(self):
        assert SKILL_MCP_SCHEMA["name"] == "skill_mcp"

    def test_schema_has_description(self):
        assert "description" in SKILL_MCP_SCHEMA
        assert "skill_name" in SKILL_MCP_SCHEMA["description"]
        assert "mcp_name" in SKILL_MCP_SCHEMA["description"]

    def test_schema_parameters_type_is_object(self):
        tool_params = SKILL_MCP_SCHEMA["parameters"]
        assert tool_params["type"] == "object"

    def test_schema_required_fields(self):
        required = SKILL_MCP_SCHEMA["parameters"]["required"]
        assert "skill_name" in required
        assert "mcp_name" in required
        assert len(required) == 2

    def test_schema_required_parameters_present(self):
        props = SKILL_MCP_SCHEMA["parameters"]["properties"]
        assert "skill_name" in props
        assert "mcp_name" in props

    def test_schema_optional_parameters_present(self):
        props = SKILL_MCP_SCHEMA["parameters"]["properties"]
        optional_params = {
            "tool_name",
            "resource_name",
            "prompt_name",
            "arguments",
            "grep",
        }  # noqa: WPS226
        assert optional_params.issubset(set(props.keys()))

    def test_schema_parameter_types(self):
        props = SKILL_MCP_SCHEMA["parameters"]["properties"]
        assert props["skill_name"]["type"] == "string"
        assert props["mcp_name"]["type"] == "string"
        assert props["tool_name"]["type"] == "string"
        assert props["resource_name"]["type"] == "string"
        assert props["prompt_name"]["type"] == "string"
        assert props["arguments"]["type"] == "object"
        assert props["grep"]["type"] == "string"


# ============================================================================
# Argument validation tests
# ============================================================================


class TestArgValidation:
    """Argument validation — tests repeat parse/assert pattern."""
    # noqa: WPS214 — test classes naturally have many methods

    def test_skill_name_missing(self):
        err = _validate_args({})
        assert err is not None
        parsed = json.loads(err)
        assert parsed["ok"] is False
        assert parsed["error_code"] == "INVALID_ARGS"
        assert "skill_name" in parsed["message"].lower()
        assert parsed["retryable"] is False

    def test_skill_name_empty_string(self):
        err = _validate_args({"skill_name": ""})
        assert err is not None
        parsed = json.loads(err)
        assert parsed["ok"] is False
        assert parsed["error_code"] == "INVALID_ARGS"

    def test_mcp_name_missing(self):
        err = _validate_args({"skill_name": "test-skill"})
        assert err is not None
        parsed = json.loads(err)
        assert parsed["ok"] is False
        assert parsed["error_code"] == "INVALID_ARGS"
        assert "mcp_name" in parsed["message"].lower()

    def test_mcp_name_empty_string(self):
        err = _validate_args({
            "skill_name": "test-skill",
            "mcp_name": "",
        })
        assert err is not None
        parsed = json.loads(err)
        assert parsed["ok"] is False
        assert parsed["error_code"] == "INVALID_ARGS"

    def test_neither_tool_resource_nor_prompt(self):
        err = _validate_args({"skill_name": "sk", "mcp_name": "mc"})
        assert err is not None
        parsed = json.loads(err)
        assert parsed["ok"] is False
        assert parsed["error_code"] == "INVALID_ARGS"
        assert "at least one" in parsed["message"].lower()

    def test_both_tool_name_and_resource_name(self):
        err = _validate_args({
            "skill_name": "sk",
            "mcp_name": "mc",
            "tool_name": "t",
            "resource_name": "r",
        })
        assert err is not None
        parsed = json.loads(err)
        assert parsed["ok"] is False
        assert parsed["error_code"] == "INVALID_ARGS"
        assert "exactly one" in parsed["message"].lower()

    def test_both_tool_name_and_prompt_name(self):
        err = _validate_args({
            "skill_name": "sk",
            "mcp_name": "mc",
            "tool_name": "t",
            "prompt_name": "p",
        })
        assert err is not None
        parsed = json.loads(err)
        assert parsed["ok"] is False
        assert parsed["error_code"] == "INVALID_ARGS"

    def test_all_three_provided(self):
        err = _validate_args({
            "skill_name": "sk",
            "mcp_name": "mc",
            "tool_name": "t",
            "resource_name": "r",
            "prompt_name": "p",
        })
        assert err is not None
        parsed = json.loads(err)
        assert parsed["ok"] is False
        assert parsed["error_code"] == "INVALID_ARGS"

    def test_valid_args_with_tool_name(self):
        err = _validate_args({
            "skill_name": "sk",
            "mcp_name": "mc",
            "tool_name": "t",
        })
        assert err is None

    def test_valid_args_with_resource_name(self):
        err = _validate_args({
            "skill_name": "sk",
            "mcp_name": "mc",
            "resource_name": "r",
        })
        assert err is None

    def test_valid_args_with_prompt_name(self):
        err = _validate_args({
            "skill_name": "sk",
            "mcp_name": "mc",
            "prompt_name": "p",
        })
        assert err is None

    def test_skill_name_wrong_type(self):
        err = _validate_args({
            "skill_name": 123,
            "mcp_name": "mc",
            "tool_name": "t",
        })
        assert err is not None
        parsed = json.loads(err)
        assert parsed["ok"] is False
        assert parsed["error_code"] == "INVALID_ARGS"


# ============================================================================
# Error response format tests
# ============================================================================


class TestErrorResponseFormat:
    def test_all_four_fields_present(self):
        resp = _build_error("TEST_ERR", "test message", retryable=True)
        parsed = json.loads(resp)
        assert parsed == {
            "ok": False,
            "error_code": "TEST_ERR",
            "message": "test message",
            "retryable": True,
        }

    def test_retryable_false(self):
        resp = _build_error("X", "m", retryable=False)
        parsed = json.loads(resp)
        assert parsed["retryable"] is False

    def test_error_is_valid_json(self):
        resp = _build_error("CODE", "msg", retryable=True)
        assert isinstance(resp, str)
        json.loads(resp)


# ============================================================================
# Skill directory resolution tests
# ============================================================================


class TestSkillDirResolution:
    def test_find_skill_dir_success(self, skill_with_mcp):
        skill_dir = skill_with_mcp("test-skill")
        resolved_dir = _find_skill_dir(
            "test-skill", [skill_dir.parent],
        )
        assert resolved_dir is not None
        assert resolved_dir.resolve() == skill_dir.resolve()

    def test_find_skill_dir_not_found(self, temp_skills_dir):
        resolved_dir = _find_skill_dir(
            "nonexistent-skill", [temp_skills_dir],
        )
        assert resolved_dir is None

    def test_find_skill_dir_no_skill_md(self, temp_skills_dir):
        (temp_skills_dir / "empty-dir").mkdir()
        resolved_dir = _find_skill_dir(
            "empty-dir", [temp_skills_dir],
        )
        assert resolved_dir is None

    def test_find_skill_dir_searches_multiple_dirs(self, skill_with_mcp):
        skill_dir = skill_with_mcp("unique-skill")
        other_dir = skill_dir.parent / "other-skills"
        other_dir.mkdir(exist_ok=True)
        resolved_dir = _find_skill_dir(
            "unique-skill", [other_dir, skill_dir.parent],
        )
        assert resolved_dir is not None
        assert resolved_dir.resolve() == skill_dir.resolve()

    def test_resolve_skill_dirs_default(self):
        dirs = _resolve_skill_dirs(None)
        assert len(dirs) == 2
        home = Path.home()
        assert dirs[0] == home / ".hermes" / "skills"
        assert dirs[1] == home / ".hermes" / "optional-skills"

    def test_resolve_skill_dirs_custom(self):
        dirs = _resolve_skill_dirs(["/custom/skills", "~/my-skills"])
        assert len(dirs) == 2
        assert dirs[0] == Path("/custom/skills")
        assert dirs[1] == Path.home() / "my-skills"


# ============================================================================
# Content extraction tests
# ============================================================================


class TestExtractContent:
    def test_extract_none_returns_empty(self):
        assert _extract_content(None) == ""

    def test_extract_plain_string(self):
        assert _extract_content("hello") == "hello"

    def test_extract_object_with_content_list(self):
        item1 = MagicMock()
        item1.text = "first"
        item1.data = None
        item2 = MagicMock()
        item2.text = "second"
        item2.data = None
        result = MagicMock()
        result.content = [item1, item2]
        assert _extract_content(result) == "first\nsecond"

    def test_extract_object_without_content_falls_back_to_str(self):
        result = MagicMock(spec=[])
        assert isinstance(_extract_content(result), str)


# ============================================================================
# create_handler tests
# ============================================================================


class TestCreateHandler:
    def test_returns_callable(self):
        manager = FakeSkillMcpManager()
        handler = create_handler(manager)
        assert callable(handler)

    def test_accepts_custom_skill_dirs(self):
        manager = FakeSkillMcpManager()
        handler = create_handler(manager, skill_dirs=["/custom"])
        assert callable(handler)


# ============================================================================
# Happy path — integration with fake manager
# ============================================================================


class TestHappyPath:
    @pytest.mark.asyncio
    async def test_valid_tool_name_returns_success(
        self, skill_with_mcp, monkeypatch,
    ):
        manager = FakeSkillMcpManager()
        skill_dir = skill_with_mcp("sqlite-skill", {
            "sqlite": {"command": "uvx", "args": ["mcp-server-sqlite"]}
        })
        handler = create_handler(
            manager, skill_dirs=[str(skill_dir.parent)],
        )

        async def fake_call_tool(name, arguments):
            result = MagicMock()
            item = MagicMock()
            item.text = '[{"1": 1}]'
            result.content = [item]
            return result

        # Pre-populate the client so we can set up call_tool
        client_key = ("default", "sqlite-skill", "sqlite")
        manager._clients[client_key] = MagicMock()
        manager._clients[client_key].call_tool = AsyncMock(
            side_effect=fake_call_tool,
        )
        manager._clients[client_key].read_resource = AsyncMock()
        manager._clients[client_key].get_prompt = AsyncMock()

        resp = await handler({
            "skill_name": "sqlite-skill",
            "mcp_name": "sqlite",
            "tool_name": "query",
            "arguments": {"sql": "SELECT 1"},
        }, session_id="default")
        parsed = json.loads(resp)
        assert parsed["ok"] is True
        assert '"1": 1' in parsed["data"]

    @pytest.mark.asyncio
    async def test_valid_resource_name_returns_success(
        self, skill_with_mcp, monkeypatch,
    ):
        manager = FakeSkillMcpManager()
        skill_dir = skill_with_mcp("docs-skill", {
            "docs": {"command": "uvx", "args": ["mcp-server-docs"]}
        })
        handler = create_handler(
            manager, skill_dirs=[str(skill_dir.parent)],
        )

        async def fake_read_resource(uri):
            result = MagicMock()
            item = MagicMock()
            item.text = "document content here"
            result.content = [item]
            return result

        client = MagicMock()
        client.call_tool = AsyncMock()
        client.read_resource = AsyncMock(side_effect=fake_read_resource)
        client.get_prompt = AsyncMock()
        manager._clients[("default", "docs-skill", "docs")] = client

        resp = await handler({
            "skill_name": "docs-skill",
            "mcp_name": "docs",
            "resource_name": "docs://readme",
        }, session_id="default")
        parsed = json.loads(resp)
        assert parsed["ok"] is True
        assert parsed["data"] == "document content here"

    @pytest.mark.asyncio
    async def test_valid_prompt_name_returns_success(
        self, skill_with_mcp, monkeypatch,
    ):
        manager = FakeSkillMcpManager()
        skill_dir = skill_with_mcp("prompt-skill", {
            "ai": {"command": "uvx", "args": ["mcp-server-ai"]}
        })
        handler = create_handler(
            manager, skill_dirs=[str(skill_dir.parent)],
        )

        async def fake_get_prompt(name, arguments):
            result = MagicMock()
            item = MagicMock()
            item.text = "prompt response"
            result.content = [item]
            return result

        client = MagicMock()
        client.call_tool = AsyncMock()
        client.read_resource = AsyncMock()
        client.get_prompt = AsyncMock(side_effect=fake_get_prompt)
        manager._clients[("default", "prompt-skill", "ai")] = client

        resp = await handler({
            "skill_name": "prompt-skill",
            "mcp_name": "ai",
            "prompt_name": "summarize",
            "arguments": {"text": "some text"},
        }, session_id="default")
        parsed = json.loads(resp)
        assert parsed["ok"] is True
        assert parsed["data"] == "prompt response"

    @pytest.mark.asyncio
    async def test_handler_calls_manager_get_or_create_client(
        self, skill_with_mcp, monkeypatch,
    ):
        manager = FakeSkillMcpManager()
        skill_dir = skill_with_mcp("track-skill", {
            "db": {"command": "python", "args": ["server.py"]}
        })
        handler = create_handler(
            manager, skill_dirs=[str(skill_dir.parent)],
        )

        async def fake_call_tool(name, arguments):
            result = MagicMock()
            item = MagicMock()
            item.text = "ok"
            result.content = [item]
            return result

        client = MagicMock()
        client.call_tool = AsyncMock(side_effect=fake_call_tool)
        client.read_resource = AsyncMock()
        client.get_prompt = AsyncMock()
        manager._clients[("sess-1", "track-skill", "db")] = client

        await handler({
            "skill_name": "track-skill",
            "mcp_name": "db",
            "tool_name": "ping",
        }, session_id="sess-1")

        assert len(manager.get_or_create_client_calls) == 1
        call = manager.get_or_create_client_calls[0]
        assert call[0] == "sess-1"
        assert call[1] == "track-skill"
        assert call[2] == "db"
        assert call[3]["command"] == "python"


# ============================================================================
# Skill/MCP resolution error tests
# ============================================================================


class TestSkillNotFound:
    @pytest.mark.asyncio
    async def test_skill_not_found_error(self, temp_skills_dir):
        manager = FakeSkillMcpManager()
        handler = create_handler(
            manager, skill_dirs=[str(temp_skills_dir)],
        )

        resp = await handler({
            "skill_name": "nonexistent-skill",
            "mcp_name": "test",
            "tool_name": "test",
        })
        parsed = json.loads(resp)
        assert parsed["ok"] is False
        assert parsed["error_code"] == "SKILL_NOT_FOUND"
        assert "nonexistent-skill" in parsed["message"]
        assert parsed["retryable"] is False

    @pytest.mark.asyncio
    async def test_no_mcp_config_error(self, skill_without_mcp):
        manager = FakeSkillMcpManager()
        skill_dir = skill_without_mcp("plain-skill")
        handler = create_handler(
            manager, skill_dirs=[str(skill_dir.parent)],
        )

        resp = await handler({
            "skill_name": "plain-skill",
            "mcp_name": "any",
            "tool_name": "test",
        })
        parsed = json.loads(resp)
        assert parsed["ok"] is False
        assert parsed["error_code"] == "NO_MCP_CONFIG"
        assert "plain-skill" in parsed["message"]
        assert parsed["retryable"] is False

    @pytest.mark.asyncio
    async def test_mcp_not_found_error(self, skill_with_mcp):
        manager = FakeSkillMcpManager()
        skill_dir = skill_with_mcp("multi-skill", {
            "sqlite": {
                "command": "uvx",
                "args": ["mcp-server-sqlite"],
            },
            "github": {
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-github"],
            },
        })
        handler = create_handler(
            manager, skill_dirs=[str(skill_dir.parent)],
        )

        resp = await handler({
            "skill_name": "multi-skill",
            "mcp_name": "unknown-server",
            "tool_name": "test",
        })
        parsed = json.loads(resp)
        assert parsed["ok"] is False
        assert parsed["error_code"] == "MCP_NOT_FOUND"
        assert "unknown-server" in parsed["message"]
        assert "multi-skill" in parsed["message"]
        assert "Available:" in parsed["message"]
        assert "github" in parsed["message"]
        assert "sqlite" in parsed["message"]
        assert parsed["retryable"] is False


# ============================================================================
# MCP error handling tests
# ============================================================================


class TestMcpConnectFailed:
    @pytest.mark.asyncio
    async def test_connection_error_returns_connect_failed(
        self, skill_with_mcp,
    ):
        manager = FakeSkillMcpManager()
        manager.configure_error(
            McpConnectionError("Connection refused"),
        )
        skill_dir = skill_with_mcp("connect-fail-skill", {
            "bad": {"command": "nonexistent", "args": []}
        })
        handler = create_handler(
            manager, skill_dirs=[str(skill_dir.parent)],
        )

        resp = await handler({
            "skill_name": "connect-fail-skill",
            "mcp_name": "bad",
            "tool_name": "test",
        })
        parsed = json.loads(resp)
        assert parsed["ok"] is False
        assert parsed["error_code"] == "MCP_CONNECT_FAILED"
        assert parsed["retryable"] is True

    @pytest.mark.asyncio
    async def test_server_exited_on_connect_returns_server_exited(
        self, skill_with_mcp,
    ):
        manager = FakeSkillMcpManager()
        manager.configure_error(
            McpServerExitedError("Server exited with code 1"),
        )
        skill_dir = skill_with_mcp("exit-skill", {
            "unstable": {"command": "python", "args": ["crash.py"]}
        })
        handler = create_handler(
            manager, skill_dirs=[str(skill_dir.parent)],
        )

        resp = await handler({
            "skill_name": "exit-skill",
            "mcp_name": "unstable",
            "tool_name": "test",
        })
        parsed = json.loads(resp)
        assert parsed["ok"] is False
        assert parsed["error_code"] == "MCP_SERVER_EXITED"
        assert parsed["retryable"] is True


class TestMcpToolErrors:
    @pytest.mark.asyncio
    async def test_tool_not_found_error(self, skill_with_mcp):
        manager = FakeSkillMcpManager()
        skill_dir = skill_with_mcp("tool-skill", {
            "server": {"command": "uvx", "args": ["mcp-server"]}
        })
        handler = create_handler(
            manager, skill_dirs=[str(skill_dir.parent)],
        )

        client = MagicMock()
        client.call_tool = AsyncMock(
            side_effect=McpToolNotFoundError(
                "Tool 'missing' not found.",
            ),
        )
        client.read_resource = AsyncMock()
        client.get_prompt = AsyncMock()
        manager._clients[("default", "tool-skill", "server")] = client

        resp = await handler({
            "skill_name": "tool-skill",
            "mcp_name": "server",
            "tool_name": "missing",
        })
        parsed = json.loads(resp)
        assert parsed["ok"] is False
        assert parsed["error_code"] == "MCP_TOOL_NOT_FOUND"
        assert parsed["retryable"] is False

    @pytest.mark.asyncio
    async def test_tool_execution_error(self, skill_with_mcp):
        manager = FakeSkillMcpManager()
        skill_dir = skill_with_mcp("exec-skill", {
            "server": {"command": "uvx", "args": ["mcp-server"]}
        })
        handler = create_handler(
            manager, skill_dirs=[str(skill_dir.parent)],
        )

        client = MagicMock()
        client.call_tool = AsyncMock(
            side_effect=McpToolExecutionError(
                "no such table: users",
            ),
        )
        client.read_resource = AsyncMock()
        client.get_prompt = AsyncMock()
        manager._clients[("default", "exec-skill", "server")] = client

        resp = await handler({
            "skill_name": "exec-skill",
            "mcp_name": "server",
            "tool_name": "query",
        })
        parsed = json.loads(resp)
        assert parsed["ok"] is False
        assert parsed["error_code"] == "MCP_TOOL_ERROR"
        assert "no such table" in parsed["message"]
        assert parsed["retryable"] is False

    @pytest.mark.asyncio
    async def test_server_exited_during_call(self, skill_with_mcp):
        manager = FakeSkillMcpManager()
        skill_dir = skill_with_mcp("crash-skill", {
            "server": {"command": "uvx", "args": ["mcp-server"]}
        })
        handler = create_handler(
            manager, skill_dirs=[str(skill_dir.parent)],
        )

        client = MagicMock()
        client.call_tool = AsyncMock(
            side_effect=McpServerExitedError(
                "Server exited with code -9",
            ),
        )
        client.read_resource = AsyncMock()
        client.get_prompt = AsyncMock()
        manager._clients[("default", "crash-skill", "server")] = client

        resp = await handler({
            "skill_name": "crash-skill",
            "mcp_name": "server",
            "tool_name": "query",
        })
        parsed = json.loads(resp)
        assert parsed["ok"] is False
        assert parsed["error_code"] == "MCP_SERVER_EXITED"
        assert parsed["retryable"] is True


# ============================================================================
# MCP SDK missing test
# ============================================================================


class TestMcpSdkMissing:
    @pytest.mark.asyncio
    async def test_sdk_missing_error(self, skill_with_mcp):
        manager = FakeSkillMcpManager()
        skill_dir = skill_with_mcp("sdk-skill", {
            "server": {"command": "uvx", "args": []}
        })
        handler = create_handler(
            manager, skill_dirs=[str(skill_dir.parent)],
        )

        with patch(
            "_tool_handler.check_mcp_sdk_available", return_value=False,
        ):
            resp = await handler({
                "skill_name": "sdk-skill",
                "mcp_name": "server",
                "tool_name": "test",
            })

        parsed = json.loads(resp)
        assert parsed["ok"] is False
        assert parsed["error_code"] == "MCP_SDK_MISSING"
        assert parsed["retryable"] is False


# ============================================================================
# grep filtering tests
# ============================================================================


class TestGrepFiltering:
    @pytest.mark.asyncio
    async def test_grep_filters_matching_lines(self, skill_with_mcp):
        manager = FakeSkillMcpManager()
        skill_dir = skill_with_mcp("grep-skill", {
            "server": {"command": "uvx", "args": ["mcp-server"]}
        })
        handler = create_handler(
            manager, skill_dirs=[str(skill_dir.parent)],
        )

        async def fake_call_tool(name, arguments):
            result = MagicMock()
            item = MagicMock()
            item.text = "line alpha\nline beta\nline gamma\n"
            result.content = [item]
            return result

        client = MagicMock()
        client.call_tool = AsyncMock(side_effect=fake_call_tool)
        client.read_resource = AsyncMock()
        client.get_prompt = AsyncMock()
        manager._clients[("default", "grep-skill", "server")] = client

        resp = await handler({
            "skill_name": "grep-skill",
            "mcp_name": "server",
            "tool_name": "list",
            "grep": "beta",
        })
        parsed = json.loads(resp)
        assert parsed["ok"] is True
        assert "beta" in parsed["data"]
        assert "alpha" not in parsed["data"]
        assert "gamma" not in parsed["data"]

    @pytest.mark.asyncio
    async def test_grep_no_matches_returns_empty(self, skill_with_mcp):
        manager = FakeSkillMcpManager()
        skill_dir = skill_with_mcp("nomatch-skill", {
            "server": {"command": "uvx", "args": ["mcp-server"]}
        })
        handler = create_handler(
            manager, skill_dirs=[str(skill_dir.parent)],
        )

        async def fake_call_tool(name, arguments):
            result = MagicMock()
            item = MagicMock()
            item.text = "hello world"
            result.content = [item]
            return result

        client = MagicMock()
        client.call_tool = AsyncMock(side_effect=fake_call_tool)
        client.read_resource = AsyncMock()
        client.get_prompt = AsyncMock()
        manager._clients[("default", "nomatch-skill", "server")] = client

        resp = await handler({
            "skill_name": "nomatch-skill",
            "mcp_name": "server",
            "tool_name": "list",
            "grep": "ZXYZZY",
        })
        parsed = json.loads(resp)
        assert parsed["ok"] is True
        assert parsed["data"] == ""

    @pytest.mark.asyncio
    async def test_invalid_regex_falls_back_to_unfiltered(
        self, skill_with_mcp,
    ):
        manager = FakeSkillMcpManager()
        skill_dir = skill_with_mcp("regex-skill", {
            "server": {"command": "uvx", "args": ["mcp-server"]}
        })
        handler = create_handler(
            manager, skill_dirs=[str(skill_dir.parent)],
        )

        async def fake_call_tool(name, arguments):
            result = MagicMock()
            item = MagicMock()
            item.text = "some output"
            result.content = [item]
            return result

        client = MagicMock()
        client.call_tool = AsyncMock(side_effect=fake_call_tool)
        client.read_resource = AsyncMock()
        client.get_prompt = AsyncMock()
        manager._clients[("default", "regex-skill", "server")] = client

        resp = await handler({
            "skill_name": "regex-skill",
            "mcp_name": "server",
            "tool_name": "list",
            "grep": "[invalid",
        })
        parsed = json.loads(resp)
        assert parsed["ok"] is True
        assert "some output" in parsed["data"]

    @pytest.mark.asyncio
    async def test_grep_without_pattern_returns_unfiltered(
        self, skill_with_mcp,
    ):
        manager = FakeSkillMcpManager()
        skill_dir = skill_with_mcp("nofilter-skill", {
            "server": {"command": "uvx", "args": ["mcp-server"]}
        })
        handler = create_handler(
            manager, skill_dirs=[str(skill_dir.parent)],
        )

        async def fake_call_tool(name, arguments):
            result = MagicMock()
            item = MagicMock()
            item.text = "line1\nline2\nline3"
            result.content = [item]
            return result

        client = MagicMock()
        client.call_tool = AsyncMock(side_effect=fake_call_tool)
        client.read_resource = AsyncMock()
        client.get_prompt = AsyncMock()
        manager._clients[("default", "nofilter-skill", "server")] = client

        resp = await handler({
            "skill_name": "nofilter-skill",
            "mcp_name": "server",
            "tool_name": "list",
        })
        parsed = json.loads(resp)
        assert parsed["ok"] is True
        assert "line1" in parsed["data"]
        assert "line2" in parsed["data"]
        assert "line3" in parsed["data"]


# ============================================================================
# Credential redaction in error messages
# ============================================================================


class TestCredentialRedaction:
    @pytest.mark.asyncio
    async def test_connection_error_redacts_credentials(
        self, skill_with_mcp,
    ):
        manager = FakeSkillMcpManager()
        manager.configure_error(
            McpConnectionError("Failed with Bearer sk-abc123secret"),
        )
        skill_dir = skill_with_mcp("redact-skill", {
            "server": {"command": "uvx", "args": ["mcp-server"]}
        })
        handler = create_handler(
            manager, skill_dirs=[str(skill_dir.parent)],
        )

        resp = await handler({
            "skill_name": "redact-skill",
            "mcp_name": "server",
            "tool_name": "test",
        })
        parsed = json.loads(resp)
        assert parsed["ok"] is False
        assert "sk-abc123" not in parsed["message"]
        assert "***" in parsed["message"]


# ============================================================================
# create_handler signature tests
# ============================================================================


class TestCreateHandlerSignature:
    @pytest.mark.asyncio
    async def test_handler_receives_kwargs(self, skill_with_mcp):
        manager = FakeSkillMcpManager()
        skill_dir = skill_with_mcp("kwargs-skill", {
            "server": {"command": "uvx", "args": ["mcp-server"]}
        })
        handler = create_handler(
            manager, skill_dirs=[str(skill_dir.parent)],
        )

        async def fake_call_tool(name, arguments):
            result = MagicMock()
            item = MagicMock()
            item.text = "ok"
            result.content = [item]
            return result

        client = MagicMock()
        client.call_tool = AsyncMock(side_effect=fake_call_tool)
        client.read_resource = AsyncMock()
        client.get_prompt = AsyncMock()
        manager._clients[
            ("my-session-id", "kwargs-skill", "server")
        ] = client

        resp = await handler({
            "skill_name": "kwargs-skill",
            "mcp_name": "server",
            "tool_name": "test",
        }, session_id="my-session-id", task_id="task-1")
        parsed = json.loads(resp)
        assert parsed["ok"] is True

        assert len(manager.get_or_create_client_calls) == 1
        assert manager.get_or_create_client_calls[0][0] == "my-session-id"

    @pytest.mark.asyncio
    async def test_handler_default_session_id(self, skill_with_mcp):
        manager = FakeSkillMcpManager()
        skill_dir = skill_with_mcp("default-sess-skill", {
            "server": {"command": "uvx", "args": ["mcp-server"]}
        })
        handler = create_handler(
            manager, skill_dirs=[str(skill_dir.parent)],
        )

        async def fake_call_tool(name, arguments):
            result = MagicMock()
            item = MagicMock()
            item.text = "ok"
            result.content = [item]
            return result

        client = MagicMock()
        client.call_tool = AsyncMock(side_effect=fake_call_tool)
        client.read_resource = AsyncMock()
        client.get_prompt = AsyncMock()
        manager._clients[
            ("default", "default-sess-skill", "server")
        ] = client

        resp = await handler({
            "skill_name": "default-sess-skill",
            "mcp_name": "server",
            "tool_name": "test",
        })
        parsed = json.loads(resp)
        assert parsed["ok"] is True
