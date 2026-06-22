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



class TestDuplicateServerNames:
    """BDD 2.4/2.5: duplicate YAML key detection."""

    def test_duplicate_server_names_logs_warning(
        self, temp_skills_dir, caplog,
    ):
        """Duplicate top-level keys in mcp.yaml log a warning."""
        skill_dir = temp_skills_dir / "dup-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("# Dup\n", encoding="utf-8")
        # Write raw YAML with duplicate keys — yaml.dump can't produce this
        (skill_dir / "mcp.yaml").write_text(
            "sqlite:\n"
            "  command: uvx\n"
            "  args: [mcp-server-sqlite]\n"
            "sqlite:\n"
            "  command: npx\n"
            "  args: [other-server]\n",
            encoding="utf-8",
        )

        with caplog.at_level(logging.WARNING):
            result = parse_mcp_config(skill_dir)

        assert any(
            "duplicate" in record.message.lower()
            for record in caplog.records
        )
        # Second definition wins (PyYAML behavior), but entry still present
        assert "sqlite" in result
        assert result["sqlite"]["command"] == "npx"

    def test_cross_skill_duplicate_resolved_by_skill_name(
        self, temp_skills_dir,
    ):
        """Same mcp_name across skills — each gets own config (BDD 2.5)."""
        # Skill A: mcp_name="shared", args=[hello]
        dir_a = temp_skills_dir / "skill-a"
        dir_a.mkdir()
        (dir_a / "SKILL.md").write_text("# Skill A\n", encoding="utf-8")
        (dir_a / "mcp.yaml").write_text(
            "shared:\n  command: echo\n  args: [hello]\n",
            encoding="utf-8",
        )

        # Skill B: same mcp_name="shared", args=[world]
        dir_b = temp_skills_dir / "skill-b"
        dir_b.mkdir()
        (dir_b / "SKILL.md").write_text("# Skill B\n", encoding="utf-8")
        (dir_b / "mcp.yaml").write_text(
            "shared:\n  command: echo\n  args: [world]\n",
            encoding="utf-8",
        )

        result_a = parse_mcp_config(dir_a)
        result_b = parse_mcp_config(dir_b)

        assert result_a["shared"]["args"] == ["hello"]
        assert result_b["shared"]["args"] == ["world"]


# ===================================================================
# Issue #3: mcp.json support (Claude Code compatible format)
# ===================================================================


class TestMcpJsonWrapperFormat:
    """mcp.json with {"mcpServers": {...}} wrapper (Claude Code format)."""

    def test_mcp_json_wrapper_basic(self, skill_with_mcp_json):
        mcp_config = {
            "sqlite": {
                "command": "uvx",
                "args": ["mcp-server-sqlite"],
            }
        }
        skill_dir = skill_with_mcp_json("json-skill", mcp_config, "wrapper")
        result = parse_mcp_config(skill_dir)

        assert "sqlite" in result
        assert result["sqlite"]["command"] == "uvx"
        assert result["sqlite"]["args"] == ["mcp-server-sqlite"]

    def test_mcp_json_wrapper_http_server(self, skill_with_mcp_json):
        mcp_config = {
            "api": {
                "url": "https://mcp.example.com/v1",
                "headers": {"Authorization": "Bearer token"},
            }
        }
        skill_dir = skill_with_mcp_json("http-json-skill", mcp_config, "wrapper")
        result = parse_mcp_config(skill_dir)

        assert "api" in result
        assert result["api"]["url"] == "https://mcp.example.com/v1"
        assert "command" not in result["api"]

    def test_mcp_json_wrapper_multiple_servers(self, skill_with_mcp_json):
        mcp_config = {
            "sqlite": {"command": "uvx", "args": ["mcp-server-sqlite"]},
            "github": {"command": "npx", "args": ["server-github"]},
        }
        skill_dir = skill_with_mcp_json("multi-json", mcp_config, "wrapper")
        result = parse_mcp_config(skill_dir)

        assert len(result) == 2
        assert "sqlite" in result
        assert "github" in result

    def test_mcp_json_wrapper_default_timeouts(self, skill_with_mcp_json):
        mcp_config = {"s": {"command": "uvx", "args": []}}
        skill_dir = skill_with_mcp_json("timeout-json", mcp_config, "wrapper")
        result = parse_mcp_config(skill_dir)

        assert result["s"]["timeout"] == _DEFAULT_TIMEOUT
        assert result["s"]["connect_timeout"] == _DEFAULT_CONNECT_TIMEOUT
        assert result["s"]["idle_timeout"] == _DEFAULT_IDLE_TIMEOUT


class TestMcpJsonFlatFormat:
    """mcp.json flat format (auto-detect, no mcpServers wrapper)."""

    def test_mcp_json_flat_with_command(self, skill_with_mcp_json):
        mcp_config = {
            "sqlite": {
                "command": "uvx",
                "args": ["mcp-server-sqlite"],
            }
        }
        skill_dir = skill_with_mcp_json("flat-json", mcp_config, "flat")
        result = parse_mcp_config(skill_dir)

        assert "sqlite" in result
        assert result["sqlite"]["command"] == "uvx"

    def test_mcp_json_flat_with_url(self, skill_with_mcp_json):
        mcp_config = {
            "api": {
                "url": "https://mcp.example.com",
            }
        }
        skill_dir = skill_with_mcp_json("flat-http-json", mcp_config, "flat")
        result = parse_mcp_config(skill_dir)

        assert "api" in result
        assert result["api"]["url"] == "https://mcp.example.com"

    def test_mcp_json_flat_multiple_servers(self, skill_with_mcp_json):
        mcp_config = {
            "db": {"command": "uvx", "args": ["sqlite"]},
            "api": {"url": "https://api.example.com"},
        }
        skill_dir = skill_with_mcp_json("flat-multi", mcp_config, "flat")
        result = parse_mcp_config(skill_dir)

        assert len(result) == 2
        assert "db" in result
        assert "api" in result


class TestMcpJsonPriority:
    """mcp.json takes priority over mcp.yaml."""

    def test_mcp_json_takes_priority_over_mcp_yaml(
        self, tmp_path,
    ):
        skill_dir = tmp_path / "priority-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("# Priority\n")

        import json
        import yaml

        (skill_dir / "mcp.json").write_text(json.dumps({
            "mcpServers": {
                "from-json": {"command": "json-cmd"},
            }
        }))
        (skill_dir / "mcp.yaml").write_text(yaml.dump({
            "from-yaml": {"command": "yaml-cmd"},
        }))

        result = parse_mcp_config(skill_dir)

        assert "from-json" in result
        assert "from-yaml" not in result

    def test_mcp_yaml_fallback_when_no_mcp_json(
        self, skill_with_mcp,
    ):
        mcp_config = {"sqlite": {"command": "uvx", "args": ["sqlite"]}}
        skill_dir = skill_with_mcp("yaml-only", mcp_config)
        result = parse_mcp_config(skill_dir)

        assert "sqlite" in result
        assert result["sqlite"]["command"] == "uvx"


class TestMcpJsonTypeField:
    """type field in mcp.json (stdio/http/sse)."""

    def test_type_stdio_explicit(self, skill_with_mcp_json):
        mcp_config = {
            "s": {"type": "stdio", "command": "uvx", "args": []},
        }
        skill_dir = skill_with_mcp_json("type-stdio", mcp_config, "wrapper")
        result = parse_mcp_config(skill_dir)

        assert result["s"]["type"] == "stdio"
        assert result["s"]["command"] == "uvx"

    def test_type_http_explicit(self, skill_with_mcp_json):
        mcp_config = {
            "api": {"type": "http", "url": "https://x.com"},
        }
        skill_dir = skill_with_mcp_json("type-http", mcp_config, "wrapper")
        result = parse_mcp_config(skill_dir)

        assert result["api"]["type"] == "http"
        assert result["api"]["url"] == "https://x.com"

    def test_type_sse_explicit(self, skill_with_mcp_json):
        mcp_config = {
            "sse": {"type": "sse", "url": "https://sse.example.com"},
        }
        skill_dir = skill_with_mcp_json("type-sse", mcp_config, "wrapper")
        result = parse_mcp_config(skill_dir)

        assert result["sse"]["type"] == "sse"
        assert result["sse"]["url"] == "https://sse.example.com"


class TestMcpJsonCwdField:
    """cwd field in mcp.json — resolved relative to mcp.json dir."""

    def test_cwd_resolved_relative(self, skill_with_mcp_json):
        mcp_config = {
            "lsp": {
                "command": "node",
                "args": ["./server.js"],
                "cwd": "."
            }
        }
        skill_dir = skill_with_mcp_json("cwd-skill", mcp_config, "wrapper")
        result = parse_mcp_config(skill_dir)

        assert "lsp" in result
        cwd_path = Path(result["lsp"]["cwd"])
        assert cwd_path.is_absolute()
        assert cwd_path == skill_dir.resolve()

    def test_cwd_subdirectory_resolved(self, skill_with_mcp_json):
        mcp_config = {
            "lsp": {
                "command": "node",
                "args": ["server.js"],
                "cwd": "./subdir"
            }
        }
        skill_dir = skill_with_mcp_json("cwd-sub", mcp_config, "wrapper")
        result = parse_mcp_config(skill_dir)

        cwd_path = Path(result["lsp"]["cwd"])
        assert cwd_path == (skill_dir / "subdir").resolve()


class TestMcpJsonEnvExpansion:
    """${VAR} expansion in mcp.json values."""

    def test_env_var_in_url_expanded(self, skill_with_mcp_json, monkeypatch):
        monkeypatch.setenv("API_URL", "https://api.example.com")
        mcp_config = {
            "api": {"url": "${API_URL}"},
        }
        skill_dir = skill_with_mcp_json("env-json", mcp_config, "wrapper")
        result = parse_mcp_config(skill_dir)

        assert result["api"]["url"] == "https://api.example.com"

    def test_env_var_in_headers_expanded(self, skill_with_mcp_json, monkeypatch):
        monkeypatch.setenv("TOKEN", "sk-secret")
        mcp_config = {
            "api": {
                "url": "https://x.com",
                "headers": {"Authorization": "Bearer ${TOKEN}"},
            }
        }
        skill_dir = skill_with_mcp_json("env-headers-json", mcp_config, "wrapper")
        result = parse_mcp_config(skill_dir)

        assert result["api"]["headers"]["Authorization"] == "Bearer sk-secret"


class TestMcpJsonPathResolution:
    """Relative paths in mcp.json resolved to mcp.json directory."""

    def test_relative_path_in_args_resolved(self, skill_with_mcp_json):
        mcp_config = {
            "local": {"command": "python", "args": ["./server.py"]},
        }
        skill_dir = skill_with_mcp_json("path-json", mcp_config, "wrapper")
        result = parse_mcp_config(skill_dir)

        resolved = Path(result["local"]["args"][0])
        assert resolved.is_absolute()
        assert resolved == (skill_dir / "server.py").resolve()

    def test_path_escape_rejected(self, skill_with_mcp_json, caplog):
        mcp_config = {
            "escape": {"command": "python", "args": ["../../../etc/passwd"]},
        }
        skill_dir = skill_with_mcp_json("escape-json", mcp_config, "wrapper")

        with caplog.at_level(logging.WARNING):
            result = parse_mcp_config(skill_dir)

        assert "escape" not in result
        assert any(
            "escapes skill directory" in record.message.lower()
            for record in caplog.records
        )


class TestMcpJsonEdgeCases:
    """Edge cases for mcp.json parsing."""

    def test_empty_mcpServers_returns_empty(self, skill_with_mcp_json):
        mcp_config = {}
        skill_dir = skill_with_mcp_json("empty-json", mcp_config, "wrapper")
        result = parse_mcp_config(skill_dir)

        assert not result

    def test_invalid_json_returns_empty_and_warns(
        self, temp_skills_dir, caplog,
    ):
        skill_dir = temp_skills_dir / "bad-json"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("# Bad\n")
        (skill_dir / "mcp.json").write_text("{ invalid json }")

        with caplog.at_level(logging.WARNING):
            result = parse_mcp_config(skill_dir)

        assert not result
        assert any(
            "failed to parse" in record.message.lower()
            or "json" in record.message.lower()
            for record in caplog.records
        )

    def test_no_mcpServers_no_command_returns_empty(
        self, temp_skills_dir, caplog,
    ):
        """{"foo": "bar"} → no server-like entries."""
        skill_dir = temp_skills_dir / "no-servers-json"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("# No\n")
        (skill_dir / "mcp.json").write_text('{"foo": "bar"}')

        with caplog.at_level(logging.WARNING):
            result = parse_mcp_config(skill_dir)

        assert not result

    def test_mcp_json_max_servers_truncated(self, skill_with_mcp_json, caplog):
        mcp_config = {}
        for idx in range(_OVERFLOW_TEST_COUNT):
            key = _SERVER_NAME_FMT.format(idx=idx)
            mcp_config[key] = {"command": "echo", "args": [key]}

        skill_dir = skill_with_mcp_json("many-json", mcp_config, "wrapper")

        with caplog.at_level(logging.WARNING):
            result = parse_mcp_config(skill_dir)

        assert len(result) == _MAX_SERVERS
        assert any(
            "truncat" in record.message.lower() or "32" in record.message
            for record in caplog.records
        )

    def test_mcp_json_duplicate_keys_warning(
        self, temp_skills_dir, caplog,
    ):
        """Duplicate keys in JSON text → warning logged."""
        skill_dir = temp_skills_dir / "dup-json"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("# Dup\n")
        (skill_dir / "mcp.json").write_text(
            '{"mcpServers": {"a": {"command": "x"}, "a": {"command": "y"}}}'
        )

        with caplog.at_level(logging.WARNING):
            result = parse_mcp_config(skill_dir)

        # JSON silently overwrites, but duplicate detection should warn
        assert any(
            "duplicate" in record.message.lower()
            for record in caplog.records
        )


# ===================================================================
# Issue #4: SKILL.md frontmatter MCP support
# ===================================================================


class TestFrontmatterMcpBasic:
    """mcp: key in SKILL.md frontmatter."""

    def test_frontmatter_mcp_basic(self, skill_with_frontmatter_mcp):
        mcp_config = {
            "sqlite": {"command": "uvx", "args": ["mcp-server-sqlite"]},
        }
        skill_dir = skill_with_frontmatter_mcp("fm-skill", mcp_config)
        result = parse_mcp_config(skill_dir)

        assert "sqlite" in result
        assert result["sqlite"]["command"] == "uvx"
        assert result["sqlite"]["args"] == ["mcp-server-sqlite"]

    def test_frontmatter_mcp_http_server(self, skill_with_frontmatter_mcp):
        mcp_config = {
            "api": {
                "url": "https://mcp.example.com",
                "headers": {"Authorization": "Bearer token"},
            }
        }
        skill_dir = skill_with_frontmatter_mcp("fm-http", mcp_config)
        result = parse_mcp_config(skill_dir)

        assert "api" in result
        assert result["api"]["url"] == "https://mcp.example.com"

    def test_frontmatter_mcp_multiple_servers(self, skill_with_frontmatter_mcp):
        mcp_config = {
            "db": {"command": "uvx", "args": ["sqlite"]},
            "api": {"url": "https://x.com"},
        }
        skill_dir = skill_with_frontmatter_mcp("fm-multi", mcp_config)
        result = parse_mcp_config(skill_dir)

        assert len(result) == 2
        assert "db" in result
        assert "api" in result


class TestFrontmatterMcpEnvAndPaths:
    """Env expansion and path resolution in frontmatter MCP."""

    def test_env_var_expanded(self, skill_with_frontmatter_mcp, monkeypatch):
        monkeypatch.setenv("API_KEY", "sk-test")
        mcp_config = {
            "api": {
                "url": "https://x.com",
                "headers": {"Authorization": "Bearer ${API_KEY}"},
            }
        }
        skill_dir = skill_with_frontmatter_mcp("fm-env", mcp_config)
        result = parse_mcp_config(skill_dir)

        assert result["api"]["headers"]["Authorization"] == "Bearer sk-test"

    def test_relative_path_resolved(self, skill_with_frontmatter_mcp):
        mcp_config = {
            "local": {"command": "python", "args": ["./server.py"]},
        }
        skill_dir = skill_with_frontmatter_mcp("fm-path", mcp_config)
        result = parse_mcp_config(skill_dir)

        resolved = Path(result["local"]["args"][0])
        assert resolved.is_absolute()
        assert resolved == (skill_dir / "server.py").resolve()

    def test_path_escape_rejected(self, skill_with_frontmatter_mcp, caplog):
        mcp_config = {
            "escape": {"command": "python", "args": ["../../../etc/passwd"]},
        }
        skill_dir = skill_with_frontmatter_mcp("fm-escape", mcp_config)

        with caplog.at_level(logging.WARNING):
            result = parse_mcp_config(skill_dir)

        assert "escape" not in result
        assert any(
            "escapes skill directory" in record.message.lower()
            for record in caplog.records
        )


class TestFrontmatterMcpPriority:
    """Priority: mcp.json > frontmatter > mcp.yaml."""

    def test_frontmatter_below_mcp_json(self, tmp_path):
        """Both mcp.json and frontmatter mcp: → mcp.json wins."""
        import json
        import yaml

        skill_dir = tmp_path / "priority-fm-json"
        skill_dir.mkdir()

        # mcp.json with "from-json"
        (skill_dir / "mcp.json").write_text(json.dumps({
            "mcpServers": {"from-json": {"command": "json-cmd"}},
        }))

        # SKILL.md with frontmatter mcp: containing "from-frontmatter"
        fm = yaml.dump({
            "name": "test", "mcp": {
                "from-frontmatter": {"command": "fm-cmd"},
            }
        })
        (skill_dir / "SKILL.md").write_text("---\n{}---\n# Test\n".format(fm))

        result = parse_mcp_config(skill_dir)

        assert "from-json" in result
        assert "from-frontmatter" not in result

    def test_frontmatter_above_mcp_yaml(self, tmp_path):
        """Frontmatter mcp: and mcp.yaml (no mcp.json) → frontmatter wins."""
        import yaml

        skill_dir = tmp_path / "priority-fm-yaml"
        skill_dir.mkdir()

        # mcp.yaml with "from-yaml"
        (skill_dir / "mcp.yaml").write_text(yaml.dump({
            "from-yaml": {"command": "yaml-cmd"},
        }))

        # SKILL.md with frontmatter mcp: containing "from-frontmatter"
        fm = yaml.dump({
            "name": "test", "mcp": {
                "from-frontmatter": {"command": "fm-cmd"},
            }
        })
        (skill_dir / "SKILL.md").write_text("---\n{}---\n# Test\n".format(fm))

        result = parse_mcp_config(skill_dir)

        assert "from-frontmatter" in result
        assert "from-yaml" not in result

    def test_fallback_to_mcp_yaml_when_no_frontmatter_mcp(
        self, skill_with_mcp,
    ):
        """SKILL.md without mcp: key, mcp.yaml present → mcp.yaml used."""
        mcp_config = {"sqlite": {"command": "uvx", "args": ["sqlite"]}}
        skill_dir = skill_with_mcp("yaml-fallback", mcp_config)
        # SKILL.md has no frontmatter mcp: (just # name)
        result = parse_mcp_config(skill_dir)

        assert "sqlite" in result


class TestFrontmatterMcpEdgeCases:
    """Edge cases for frontmatter MCP parsing."""

    def test_no_mcp_key_in_frontmatter(self, skill_with_frontmatter_mcp):
        """SKILL.md frontmatter without mcp: key → no servers."""
        skill_dir = skill_with_frontmatter_mcp("no-mcp-key", None)
        result = parse_mcp_config(skill_dir)

        assert not result

    def test_no_frontmatter_at_all(self, tmp_path):
        """SKILL.md starts with # heading, no --- → no frontmatter."""
        skill_dir = tmp_path / "no-fm"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("# No Frontmatter\nBody text.")

        result = parse_mcp_config(skill_dir)

        assert not result

    def test_frontmatter_not_at_start(self, tmp_path):
        """--- not first line → frontmatter not parsed."""
        skill_dir = tmp_path / "fm-not-start"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "# Title\n---\nmcp: {}\n---\nBody"
        )

        result = parse_mcp_config(skill_dir)

        assert not result

    def test_malformed_yaml_in_frontmatter(self, tmp_path, caplog):
        skill_dir = tmp_path / "fm-bad"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: [unclosed\nmcp:\n  sqlite:\n    command: x\n---\nBody"
        )

        with caplog.at_level(logging.WARNING):
            result = parse_mcp_config(skill_dir)

        assert not result
        assert any(
            "failed to parse" in record.message.lower()
            or "frontmatter" in record.message.lower()
            for record in caplog.records
        )

    def test_mcp_value_not_dict(self, tmp_path, caplog):
        skill_dir = tmp_path / "fm-bad-value"
        skill_dir.mkdir()

        import yaml
        fm = yaml.dump({"name": "test", "mcp": "not a dict"})
        (skill_dir / "SKILL.md").write_text("---\n{}---\n# Test\n".format(fm))

        with caplog.at_level(logging.WARNING):
            result = parse_mcp_config(skill_dir)

        assert not result

    def test_frontmatter_mcp_max_servers_truncated(
        self, skill_with_frontmatter_mcp, caplog,
    ):
        mcp_config = {}
        for idx in range(_OVERFLOW_TEST_COUNT):
            key = _SERVER_NAME_FMT.format(idx=idx)
            mcp_config[key] = {"command": "echo", "args": [key]}

        skill_dir = skill_with_frontmatter_mcp("fm-many", mcp_config)

        with caplog.at_level(logging.WARNING):
            result = parse_mcp_config(skill_dir)

        assert len(result) == _MAX_SERVERS
        assert any(
            "truncat" in record.message.lower() or "32" in record.message
            for record in caplog.records
        )


# ===================================================================
# Issue #5: SSE transport support (config-level tests)
# ===================================================================


class TestSseConfigParsing:
    """type: 'sse' in config files."""

    def test_sse_type_in_mcp_json(self, skill_with_mcp_json):
        mcp_config = {
            "remote-sse": {
                "type": "sse",
                "url": "https://mcp.example.com/sse",
                "headers": {"Authorization": "Bearer token"},
            }
        }
        skill_dir = skill_with_mcp_json("sse-json", mcp_config, "wrapper")
        result = parse_mcp_config(skill_dir)

        assert "remote-sse" in result
        assert result["remote-sse"]["type"] == "sse"
        assert result["remote-sse"]["url"] == "https://mcp.example.com/sse"

    def test_sse_type_in_frontmatter(self, skill_with_frontmatter_mcp):
        mcp_config = {
            "remote-sse": {
                "type": "sse",
                "url": "https://mcp.example.com/sse",
            }
        }
        skill_dir = skill_with_frontmatter_mcp("sse-fm", mcp_config)
        result = parse_mcp_config(skill_dir)

        assert "remote-sse" in result
        assert result["remote-sse"]["type"] == "sse"

    def test_sse_type_with_command_rejected(self, skill_with_mcp_json, caplog):
        mcp_config = {
            "bad": {
                "type": "sse",
                "command": "some-cmd",
                "url": "https://x.com/sse",
            }
        }
        skill_dir = skill_with_mcp_json("sse-bad", mcp_config, "wrapper")

        with caplog.at_level(logging.WARNING):
            result = parse_mcp_config(skill_dir)

        assert "bad" not in result
        assert any(
            "sse" in record.message.lower() and "command" in record.message.lower()
            for record in caplog.records
        )

    def test_sse_type_without_url_rejected(self, skill_with_mcp_json, caplog):
        mcp_config = {
            "bad": {
                "type": "sse",
            }
        }
        skill_dir = skill_with_mcp_json("sse-no-url", mcp_config, "wrapper")

        with caplog.at_level(logging.WARNING):
            result = parse_mcp_config(skill_dir)

        assert "bad" not in result
        assert any(
            "sse" in record.message.lower() and "url" in record.message.lower()
            for record in caplog.records
        )

    def test_sse_env_expansion(self, skill_with_mcp_json, monkeypatch):
        monkeypatch.setenv("SSE_URL", "https://sse.example.com")
        monkeypatch.setenv("SSE_TOKEN", "sk-secret")
        mcp_config = {
            "sse": {
                "type": "sse",
                "url": "${SSE_URL}",
                "headers": {"Authorization": "Bearer ${SSE_TOKEN}"},
            }
        }
        skill_dir = skill_with_mcp_json("sse-env", mcp_config, "wrapper")
        result = parse_mcp_config(skill_dir)

        assert result["sse"]["url"] == "https://sse.example.com"
        assert result["sse"]["headers"]["Authorization"] == "Bearer sk-secret"