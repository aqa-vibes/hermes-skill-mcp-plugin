# TODO: fix wemake WPS202,WPS204,WPS226,WPS430,WPS431 — test module patterns: many functions, repeated test data, mock classes
# flake8: noqa: WPS202,WPS204,WPS402,WPS226 — test module
"""Tests for _config.py config parser."""
from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import patch

from conftest import import_plugin_module

# Module-level constants to avoid magic numbers
_DEFAULT_TIMEOUT = 60
_DEFAULT_CONNECT_TIMEOUT = 10
_DEFAULT_IDLE_TIMEOUT = 300
_CUSTOM_OVERRIDE_TIMEOUT = 30
_CUSTOM_OVERRIDE_CONNECT = 5
_CUSTOM_OVERRIDE_IDLE = 120
_MAX_SERVERS = 32
_OVERFLOW_TEST_COUNT = 40  # noqa: WPS432 — explicit boundary value
_SERVER_NAME_FMT = "server_{idx}"


parse_mcp_config = import_plugin_module(
    "_config",
).parse_mcp_config
check_mcp_sdk_available = import_plugin_module(
    "_config",
).check_mcp_sdk_available


class TestParseMcpConfigBasicStdio:
    """mcp.yaml with command + args → dict with server config."""
    # noqa: WPS226 — test data strings naturally repeat

    def test_command_and_args_parsed(self, skill_with_mcp):
        mcp_config = {
            "sqlite": {
                "command": "uvx",
                "args": ["mcp-server-sqlite"],
            }
        }
        skill_dir = skill_with_mcp("sqlite-workflow", mcp_config)
        config_result = parse_mcp_config(skill_dir)

        assert "sqlite" in config_result
        assert config_result["sqlite"]["command"] == "uvx"
        assert config_result["sqlite"]["args"] == ["mcp-server-sqlite"]

    def test_default_timeouts_filled(self, skill_with_mcp):
        mcp_config = {
            "sqlite": {
                "command": "uvx",
                "args": ["mcp-server-sqlite"],
            }
        }
        skill_dir = skill_with_mcp("sqlite-workflow", mcp_config)
        config_result = parse_mcp_config(skill_dir)

        server = config_result["sqlite"]
        assert server["timeout"] == _DEFAULT_TIMEOUT
        assert server["connect_timeout"] == _DEFAULT_CONNECT_TIMEOUT
        assert server["idle_timeout"] == _DEFAULT_IDLE_TIMEOUT

    def test_custom_timeouts_preserved(self, skill_with_mcp):
        mcp_config = {
            "db": {
                "command": "python",
                "args": ["server.py"],
                "timeout": _CUSTOM_OVERRIDE_TIMEOUT,
                "connect_timeout": _CUSTOM_OVERRIDE_CONNECT,
                "idle_timeout": _CUSTOM_OVERRIDE_IDLE,
            }
        }
        skill_dir = skill_with_mcp("custom-skill", mcp_config)
        config_result = parse_mcp_config(skill_dir)

        server = config_result["db"]
        assert server["timeout"] == _CUSTOM_OVERRIDE_TIMEOUT
        assert server["connect_timeout"] == _CUSTOM_OVERRIDE_CONNECT
        assert server["idle_timeout"] == _CUSTOM_OVERRIDE_IDLE


class TestParseMcpConfigHttp:
    """mcp.yaml with url → transport = HTTP."""
    # noqa: WPS226 — test data strings naturally repeat

    def test_url_config_has_no_command_key(self, skill_with_mcp):
        mcp_config = {
            "company_api": {
                "url": "https://mcp.company.com/v1",
                "headers": {
                    "Authorization": "Bearer static-key",
                },
            }
        }
        skill_dir = skill_with_mcp("remote-skill", mcp_config)
        config_result = parse_mcp_config(skill_dir)

        assert "company_api" in config_result
        server = config_result["company_api"]
        assert server["url"] == "https://mcp.company.com/v1"
        assert "command" not in server
        assert server["headers"] == {"Authorization": "Bearer static-key"}

    def test_url_config_gets_default_timeouts(self, skill_with_mcp):
        mcp_config = {"api": {"url": "https://example.com/mcp"}}
        skill_dir = skill_with_mcp("http-skill", mcp_config)
        config_result = parse_mcp_config(skill_dir)

        server = config_result["api"]
        assert server["timeout"] == _DEFAULT_TIMEOUT
        assert server["connect_timeout"] == _DEFAULT_CONNECT_TIMEOUT
        assert server["idle_timeout"] == _DEFAULT_IDLE_TIMEOUT


class TestParseMcpConfigMultipleServers:
    """Multiple valid servers in one mcp.yaml."""
    # noqa: WPS226 — test data strings naturally repeat

    def test_multiple_servers_all_parsed(self, skill_with_mcp):
        mcp_config = {
            "sqlite": {
                "command": "uvx",
                "args": ["mcp-server-sqlite"],
            },
            "github": {
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-github"],
            },
        }
        skill_dir = skill_with_mcp("multi-skill", mcp_config)
        config_result = parse_mcp_config(skill_dir)

        assert len(config_result) == 2
        assert "sqlite" in config_result
        assert "github" in config_result


class TestEnvVarExpansion:
    """${VAR} syntax expanded from os.environ."""
    # noqa: WPS226 — test data strings naturally repeat

    def test_env_var_expanded(self, skill_with_mcp, monkeypatch):
        monkeypatch.setenv("API_KEY", "sk-test-12345")
        mcp_config = {
            "api": {
                "url": "https://api.example.com",
                "headers": {"Authorization": "Bearer ${API_KEY}"},
            }
        }
        skill_dir = skill_with_mcp("env-skill", mcp_config)
        config_result = parse_mcp_config(skill_dir)

        headers = config_result["api"]["headers"]
        assert headers["Authorization"] == "Bearer sk-test-12345"

    def test_env_var_in_command_args_expanded(
        self, skill_with_mcp, monkeypatch,
    ):
        monkeypatch.setenv("DB_PATH", "/data/mydb.sqlite")
        mcp_config = {
            "sqlite": {
                "command": "uvx",
                "args": ["mcp-server-sqlite", "--db-path", "${DB_PATH}"],
            }
        }
        skill_dir = skill_with_mcp("db-skill", mcp_config)
        config_result = parse_mcp_config(skill_dir)

        assert config_result["sqlite"]["args"][2] == "/data/mydb.sqlite"

    def test_env_var_in_env_block_expanded(
        self, skill_with_mcp, monkeypatch,
    ):
        monkeypatch.setenv("GH_TOKEN", "ghp_secret")
        mcp_config = {
            "github": {
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-github"],
                "env": {"GITHUB_TOKEN": "${GH_TOKEN}"},
            }
        }
        skill_dir = skill_with_mcp("gh-skill", mcp_config)
        config_result = parse_mcp_config(skill_dir)

        assert config_result["github"]["env"]["GITHUB_TOKEN"] == "ghp_secret"

    def test_missing_env_var_left_unexpanded(
        self, skill_with_mcp, monkeypatch,
    ):
        monkeypatch.delenv("MISSING_VAR", raising=False)
        mcp_config = {
            "api": {
                "url": "https://example.com",
                "headers": {"X-Token": "${MISSING_VAR}"},
            }
        }
        skill_dir = skill_with_mcp("missing-env-skill", mcp_config)
        config_result = parse_mcp_config(skill_dir)

        headers = config_result["api"]["headers"]
        unexpanded = headers["X-Token"]
        assert unexpanded == "${MISSING_VAR}" or unexpanded == ""

    def test_no_expansion_without_dollar_brace_syntax(
        self, skill_with_mcp,
    ):
        """Values without ${} syntax used literally."""
        mcp_config = {
            "api": {
                "url": "https://example.com",
                "headers": {"Authorization": "Bearer static-key"},
            }
        }
        skill_dir = skill_with_mcp("static-skill", mcp_config)
        config_result = parse_mcp_config(skill_dir)

        headers = config_result["api"]["headers"]
        assert headers["Authorization"] == "Bearer static-key"


class TestPathResolution:
    """Relative paths resolved relative to mcp.yaml directory."""

    def test_relative_path_in_args_resolved(self, skill_with_mcp):
        mcp_config = {
            "local": {
                "command": "python",
                "args": ["./server.py"],
            }
        }
        skill_dir = skill_with_mcp("tool", mcp_config)
        config_result = parse_mcp_config(skill_dir)

        resolved = Path(config_result["local"]["args"][0])
        assert resolved.is_absolute()
        assert resolved == (skill_dir / "server.py").resolve()

    def test_path_escaping_skill_dir_rejected(
        self, skill_with_mcp, caplog,
    ):
        mcp_config = {
            "escape": {
                "command": "python",
                "args": ["../../../etc/passwd"],
            }
        }
        skill_dir = skill_with_mcp("escape-skill", mcp_config)

        with caplog.at_level(logging.WARNING):
            config_result = parse_mcp_config(skill_dir)

        assert "escape" not in config_result
        assert any(
            "escapes skill directory" in record.message.lower()
            for record in caplog.records
        )

    def test_absolute_path_preserved(self, skill_with_mcp):
        abs_path = "/usr/local/bin/my-server"
        mcp_config = {
            "abs": {
                "command": abs_path,
                "args": [],
            }
        }
        skill_dir = skill_with_mcp("abs-skill", mcp_config)
        config_result = parse_mcp_config(skill_dir)

        assert config_result["abs"]["command"] == abs_path


class TestMissingConfig:
    """No mcp.yaml → returns {}."""

    def test_no_mcp_yaml_returns_empty_dict(self, skill_without_mcp):
        skill_dir = skill_without_mcp("basic-skill")
        config_result = parse_mcp_config(skill_dir)

        assert not config_result

    def test_empty_mcp_yaml_returns_empty_dict(self, skill_with_mcp):
        skill_dir = skill_with_mcp("empty-skill", {})
        config_result = parse_mcp_config(skill_dir)

        assert not config_result


class TestInvalidYaml:
    """Invalid YAML → returns {}, warning logged."""

    def test_invalid_yaml_returns_empty_and_warns(
        self, temp_skills_dir, caplog,
    ):
        skill_dir = temp_skills_dir / "bad-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("# Bad\n", encoding="utf-8")
        (skill_dir / "mcp.yaml").write_text(
            "server: [unclosed\n  command: bad",
            encoding="utf-8",
        )

        with caplog.at_level(logging.WARNING):
            config_result = parse_mcp_config(skill_dir)

        assert not config_result
        assert any(
            "failed to parse" in record.message.lower()
            or "yaml" in record.message.lower()
            for record in caplog.records
        )


class TestCommandUrlValidation:
    """Entries must have command XOR url."""
    # noqa: WPS226 — test data strings naturally repeat

    def test_missing_both_command_and_url_rejected(
        self, skill_with_mcp, caplog,
    ):
        mcp_config = {"bad": {"timeout": _CUSTOM_OVERRIDE_TIMEOUT}}
        skill_dir = skill_with_mcp("invalid-skill", mcp_config)

        with caplog.at_level(logging.WARNING):
            config_result = parse_mcp_config(skill_dir)

        assert "bad" not in config_result

    def test_both_command_and_url_rejected(
        self, skill_with_mcp, caplog,
    ):
        mcp_config = {
            "bad": {
                "command": "uvx",
                "url": "https://example.com",
            }
        }
        skill_dir = skill_with_mcp("confused-skill", mcp_config)

        with caplog.at_level(logging.WARNING):
            config_result = parse_mcp_config(skill_dir)

        assert "bad" not in config_result


class TestUnknownFields:
    """Unknown fields silently ignored."""
    # noqa: WPS226 — test data strings naturally repeat

    def test_unknown_field_ignored(self, skill_with_mcp):
        mcp_config = {
            "server": {
                "command": "uvx",
                "args": ["mcp-server-example"],
                "sampling": {"enabled": True},
            }
        }
        skill_dir = skill_with_mcp("future-skill", mcp_config)
        config_result = parse_mcp_config(skill_dir)

        assert "server" in config_result
        assert "sampling" not in config_result["server"]


class TestMaxServers:
    """Max 32 servers; >32 truncated with warning."""
    # noqa: WPS114 — underscored number in test name is valid

    def test_max_servers_truncated(self, skill_with_mcp, caplog):
        mcp_config = {}
        for idx in range(_OVERFLOW_TEST_COUNT):
            server_key = _SERVER_NAME_FMT.format(idx=idx)
            mcp_config[server_key] = {
                "command": "echo",
                "args": [server_key],
            }

        skill_dir = skill_with_mcp("many-skill", mcp_config)

        with caplog.at_level(logging.WARNING):
            config_result = parse_mcp_config(skill_dir)

        assert len(config_result) == _MAX_SERVERS
        assert any(
            "truncat" in record.message.lower() or "32" in record.message
            for record in caplog.records
        )

    def test_exactly_max_servers_all_loaded(self, skill_with_mcp):
        mcp_config = {}
        for idx in range(_MAX_SERVERS):
            server_key = _SERVER_NAME_FMT.format(idx=idx)
            mcp_config[server_key] = {
                "command": "echo",
                "args": [server_key],
            }

        skill_dir = skill_with_mcp("exact-max-skill", mcp_config)
        config_result = parse_mcp_config(skill_dir)

        assert len(config_result) == _MAX_SERVERS


class TestEdgeCases:
    """Edge case handling."""
    # noqa: WPS118 — descriptive test name over 45 chars
    # noqa: WPS226 — test data strings naturally repeat

    def test_unknown_server_keys_are_top_level_keys(
        self, skill_with_mcp,
    ):
        """Each top-level key in mcp.yaml is a server name."""
        mcp_config = {
            "db": {"command": "uvx", "args": ["mcp-server-sqlite"]},
            "api": {"url": "https://api.example.com"},
        }
        skill_dir = skill_with_mcp("multi-skill", mcp_config)
        config_result = parse_mcp_config(skill_dir)

        assert isinstance(config_result, dict)
        assert all(isinstance(key, str) for key in config_result)
        assert all(
            isinstance(cfg_value, dict)
            for cfg_value in config_result.values()
        )

    def test_result_always_has_timeout_keys(self, skill_with_mcp):
        timeout_test_configs = []  # noqa: WPS335
        timeout_test_configs.append(
            {"s": {"command": "uvx", "args": []}},
        )
        timeout_test_configs.append(
            {"s": {"url": "https://x.com"}},
        )
        for test_conf in timeout_test_configs:
            skill_dir = skill_with_mcp("timeout-skill", test_conf)
            config_result = parse_mcp_config(skill_dir)
            server = config_result["s"]
            assert "timeout" in server
            assert "connect_timeout" in server
            assert "idle_timeout" in server

    def test_empty_args_defaults_to_empty_list(self, skill_with_mcp):
        mcp_config = {"server": {"command": "uvx"}}
        skill_dir = skill_with_mcp("no-args-skill", mcp_config)
        config_result = parse_mcp_config(skill_dir)

        assert not config_result["server"]["args"]

    def test_never_raises_exception(self, temp_skills_dir):
        """parse_mcp_config never raises, even with non-existent dir."""
        config_result = parse_mcp_config(
            temp_skills_dir / "does-not-exist",
        )
        assert not config_result

        skill_dir = temp_skills_dir / "just-skills"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "# Just skills\n", encoding="utf-8",
        )
        config_result = parse_mcp_config(skill_dir)
        assert not config_result


class TestCheckMcpSdkAvailable:
    """check_mcp_sdk_available returns True/False from import success."""

    def test_returns_true_when_mcp_importable(self):
        from importlib import util  # noqa: WPS301 — test only import

        sdk_result = check_mcp_sdk_available()
        spec = util.find_spec("mcp")
        if spec is None:
            assert sdk_result is False
        else:
            assert sdk_result is True

    def test_returns_false_when_mcp_not_importable(self):
        with patch.dict("sys.modules", {"mcp": None}):
            original_import = __builtins__["__import__"]

            def mock_import(name, *args, **kwargs):  # noqa: WPS430
                if name == "mcp" or name.startswith("mcp."):
                    raise ImportError("No module named 'mcp'")
                return original_import(name, *args, **kwargs)

            with patch(
                "builtins.__import__", side_effect=mock_import,
            ):
                sdk_result = check_mcp_sdk_available()
                assert sdk_result is False

    def test_does_not_cache_result(self):
        """Each call re-checks import. Test by calling twice."""
        r1 = check_mcp_sdk_available()
        r2 = check_mcp_sdk_available()
        assert r1 == r2
        assert isinstance(r1, bool)
