"""
E2E tests for skill-mcp plugin.

Verifies: plugin → MCP config → agent calls skill_mcp
→ gets unguessable magic phrase from MCP server.
"""
import importlib
import os
import subprocess
from pathlib import Path

import pytest

from constants import (
    CLI_TIMEOUT, CONFIG_PATH, MAGIC_PHRASE, MODEL_KEY,
)
from constants import (
    PLUGIN_PATH, SERVER_NAME, SKILL_NAME, SKILL_PATH, SKILLS_DIR, TOOL_NAME,
)
from constants import connected_manager, make_manager, run_hermes_e2e


def import_plugin_module(module_name: str):
    """Import a module from the skill-mcp plugin directory."""
    plugin_dir = Path(PLUGIN_PATH)
    file_name = module_name.split(".")[-1]
    spec = importlib.util.spec_from_file_location(
        module_name,
        plugin_dir / "{}.py".format(file_name),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestPluginInstallation:
    """Test that plugin is installed and discoverable."""

    def test_plugin_directory_exists(self):
        assert Path(PLUGIN_PATH).is_dir()

    def test_plugin_has_init(self):
        assert (Path(PLUGIN_PATH) / "__init__.py").exists()

    def test_plugin_modules_present(self):
        path = Path(PLUGIN_PATH)
        for mod in ("_config.py", "_connection.py", "_skill_view_hook.py"):
            assert (path / mod).exists(), "Missing {}".format(mod)

    def test_plugin_imports_cleanly(self):
        mod = import_plugin_module("_metadata")
        assert mod.PLUGIN_VERSION == "0.1.0"


class TestMcpConfigParsing:
    """Test mcp.yaml parsing from skill."""

    def test_parse_config(self):
        parse_config = import_plugin_module("_config").parse_mcp_config
        config = parse_config(Path(SKILL_PATH))
        assert config is not None
        assert SERVER_NAME in config
        assert config[SERVER_NAME]["command"] == "python3"

    def test_parse_nonexistent(self, tmp_path):
        parse_config = import_plugin_module("_config").parse_mcp_config
        empty_dir = tmp_path / "no-mcp-skill"
        empty_dir.mkdir()
        assert parse_config(empty_dir) is None


class TestSkillViewHook:
    """Test skill view hook shows MCP info."""

    def test_shows_mcp(self):
        hook = import_plugin_module("_skill_view_hook").skill_view_extra
        output = hook(Path(SKILL_PATH))
        assert output is not None
        assert "MCP Servers" in output
        assert SERVER_NAME in output

    def test_no_mcp_returns_none(self, tmp_path):
        hook = import_plugin_module("_skill_view_hook").skill_view_extra
        empty_dir = tmp_path / "plain-skill"
        empty_dir.mkdir()
        assert hook(empty_dir) is None


class TestMcpConnection:
    """Test real MCP connections to magic MCP server."""

    @pytest.fixture
    def server_config(self):
        parse_config = import_plugin_module("_config").parse_mcp_config
        return parse_config(Path(SKILL_PATH))[SERVER_NAME]

    @pytest.mark.asyncio
    async def test_connect(self, server_config):
        async with connected_manager(
            SKILL_NAME, SERVER_NAME, server_config,
        ):
            manager = make_manager()
            tools = await manager.connect(
                manager.get_or_create_client(
                    SKILL_NAME, SERVER_NAME, server_config,
                ),
            ).list_tools()
        tool_names = {entry.name for entry in tools.tools}
        assert TOOL_NAME in tool_names

    @pytest.mark.asyncio
    async def test_call_tool(self, server_config):
        manager = make_manager()
        tool_response = await manager.call_tool(
            skill_name=SKILL_NAME,
            mcp_name=SERVER_NAME,
            server_config=server_config,
            tool_name=TOOL_NAME,
        )
        assert tool_response is not None
        assert tool_response.content

    @pytest.mark.asyncio
    async def test_reuse(self, server_config):
        manager = make_manager()
        first = manager.get_or_create_client(
            SKILL_NAME, SERVER_NAME, server_config,
        )
        second = manager.get_or_create_client(
            SKILL_NAME, SERVER_NAME, server_config,
        )
        assert first is second


class TestHermesCLI:
    """Test Hermes CLI discovers and enables skill-mcp toolset."""

    def test_tools_list(self):
        cmd_result = subprocess.run(
            ["hermes", "tools", "list"],
            capture_output=True, text=True, timeout=CLI_TIMEOUT,
        )
        assert cmd_result.returncode == 0

    def test_skills_list(self):
        cmd_result = subprocess.run(
            ["hermes", "skills", "list"],
            capture_output=True, text=True, timeout=CLI_TIMEOUT,
        )
        assert cmd_result.returncode == 0

    def test_config_has_skills_dir(self):
        import yaml
        with open(CONFIG_PATH) as config_file:
            config = yaml.safe_load(config_file)
        skill_dirs = config.get("skills", {}).get("external_dirs", [])
        assert SKILLS_DIR in skill_dirs


class TestAgentE2E:
    """End-to-end: Hermes agent loads skill, calls skill_mcp tool."""

    @pytest.fixture(autouse=True)
    def require_key(self):
        if not os.environ.get("HERMES_API_KEY"):
            pytest.skip("HERMES_API_KEY not set")

    def test_magic_secret(self, e2e_config):
        """Agent calls skill_mcp → gets unguessable phrase from MCP."""
        prompt = (
            "Load skill '{0}'. "
            "Use skill_mcp to call {1} from the {2} MCP server. "
            "Output ONLY the exact phrase returned. Nothing else."
        ).format(SKILL_NAME, TOOL_NAME, SERVER_NAME)

        agent_output = run_hermes_e2e(
            ["-z", prompt, "-m", e2e_config[MODEL_KEY], "chat"],
            e2e_config,
        )

        err_msg = "Missing '{0}' in agent output: {1}"
        assert MAGIC_PHRASE in agent_output, err_msg.format(
            MAGIC_PHRASE, agent_output[:len(agent_output)],
        )
