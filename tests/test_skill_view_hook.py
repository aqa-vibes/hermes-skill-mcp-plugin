"""Tests for _skill_view_hook.py."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml

from _skill_view_hook import create_hook, skill_view_extra, _build_mcp_section


SKILL_FILE = "SKILL.md"
MCP_FILE = "mcp.yaml"
SKILL_VIEW = "skill_view"
SECTION_TITLE = "## MCP Servers"
STATIC_NOTE = "Static config"


def _make_skill_view_result(path: str, ok: bool = True) -> str:
    return json.dumps(
        dict(
            ok=ok,
            path=path,
            name=Path(path).name,
            description="A test skill",
        ),
    )


class TestSkillViewHook:
    def test_helpers_work(self, temp_skills_dir: Path) -> None:
        skill_dir = temp_skills_dir / "my-skill"
        skill_dir.mkdir()
        skill_md = skill_dir / SKILL_FILE
        mcp_yaml = skill_dir / MCP_FILE
        skill_md.write_text("# My Skill\n", encoding="utf-8")  # noqa: WPS226

        config = {
            "sqlite": {
                "command": "uvx",
                "args": ["mcp-server-sqlite"],
            },
        }
        mcp_yaml.write_text(yaml.safe_dump(config), encoding="utf-8")

        section = _build_mcp_section(config)

        assert callable(create_hook())
        assert section.startswith(SECTION_TITLE)
        assert skill_view_extra(skill_dir) == section

    @pytest.mark.parametrize(
        ("tool_name", "hook_result", "omit_tool_name"),
        [
            ("terminal", "some output", False),
            ("execute_code", "{}", False),
            ("skill_mcp", "{}", False),
            (None, "{}", True),
            (SKILL_VIEW, "not valid json", False),
            (SKILL_VIEW, object(), False),
            (SKILL_VIEW, None, False),
            (SKILL_VIEW, "[1, 2, 3]", False),
            (SKILL_VIEW, json.dumps(dict(ok=True)), False),
        ],
    )
    def test_bad_inputs_return_none(
        self,
        tool_name: str | None,
        hook_result: object,
        omit_tool_name: bool,
    ) -> None:
        hook = create_hook()
        kwargs = dict(result=hook_result, args={})

        if omit_tool_name:
            hook_output = hook(**kwargs)
        else:
            hook_output = hook(tool_name=tool_name, **kwargs)

        assert hook_output is None

    @pytest.mark.parametrize(
        "name", ["ok_false", "file_path", "missing_path"],
    )
    def test_bad_paths_return_none(
        self,
        temp_skills_dir: Path,
        name: str,
    ) -> None:
        hook = create_hook()

        if name == "ok_false":
            skill_dir = temp_skills_dir / "no-ok-skill"
            skill_dir.mkdir()
            (skill_dir / SKILL_FILE).write_text("# No OK\n", encoding="utf-8")
            hook_output = hook(
                tool_name=SKILL_VIEW,
                result=_make_skill_view_result(str(skill_dir), ok=False),
                args={},
            )
        elif name == "file_path":
            file_path = temp_skills_dir / "not-a-dir.txt"
            file_path.write_text("hello", encoding="utf-8")
            hook_output = hook(
                tool_name=SKILL_VIEW,
                result=json.dumps(dict(ok=True, path=str(file_path))),
                args={},
            )
        else:
            hook_output = hook(
                tool_name=SKILL_VIEW,
                result=json.dumps(
                    dict(ok=True, path=str(temp_skills_dir / "missing")),
                ),
                args={},
            )

        assert hook_output is None

    @pytest.mark.parametrize(
        ("server_name", "config", "expected_bits"),
        [
            (
                "stdio",
                {
                    "command": "uvx",
                    "args": ["mcp-server-sqlite", "--db", "data.db"],
                },
                ("### stdio", "uvx mcp-server-sqlite --db data.db"),
            ),
            (
                "http",
                {
                    "url": "https://mcp.example.com/v1",
                    "headers": {
                        "Authorization": "Bearer sk-abc123secret",
                    },
                },
                ("### http", "url: https://mcp.example.com/v1"),
            ),
        ],
    )
    def test_stdio_and_http_append(
        self,
        temp_skills_dir: Path,
        server_name: str,
        config: dict[str, object],
        expected_bits: tuple[str, ...],
    ) -> None:
        skill_dir = temp_skills_dir / f"{server_name}-skill"
        skill_dir.mkdir()
        skill_md = skill_dir / SKILL_FILE
        mcp_yaml = skill_dir / MCP_FILE
        skill_md.write_text("# Skill\n", encoding="utf-8")
        mcp_yaml.write_text(
            yaml.safe_dump({server_name: config}),
            encoding="utf-8",
        )

        hook = create_hook()
        hook_output = hook(
            tool_name=SKILL_VIEW,
            result=_make_skill_view_result(str(skill_dir)),
            args={},
        )

        assert hook_output is not None and all(
            bit in hook_output for bit in expected_bits
        )
        if server_name == "http":
            assert "sk-abc123secret" not in hook_output

    @pytest.mark.parametrize(
        "yaml_text",
        [
            None,
            "{}\n",
            "server: [unclosed\n  command: bad",
        ],
    )
    def test_missing_or_bad_mcp_yaml(
        self,
        temp_skills_dir: Path,
        yaml_text: str | None,
    ) -> None:
        skill_dir = temp_skills_dir / "bad-mcp-skill"
        skill_dir.mkdir()
        skill_md = skill_dir / SKILL_FILE
        skill_md.write_text("# Skill\n", encoding="utf-8")
        if yaml_text is not None:
            (skill_dir / MCP_FILE).write_text(yaml_text, encoding="utf-8")

        hook = create_hook()
        hook_output = hook(
            tool_name=SKILL_VIEW,
            result=_make_skill_view_result(str(skill_dir)),
            args={},
        )

        assert hook_output is None

    def test_multiple_servers_redact_and_preserve(
        self,
        temp_skills_dir: Path,
    ) -> None:
        skill_dir = temp_skills_dir / "mixed-skill"
        skill_dir.mkdir()
        (skill_dir / SKILL_FILE).write_text(
            "# Skill\n", encoding="utf-8",  # noqa: WPS226
        )

        mcp_yaml = skill_dir / MCP_FILE
        config = {
            "local-db": {
                "command": "python",
                "args": ["-m", "db_server"],
                "timeout": 30,
                "connect_timeout": 5,
                "idle_timeout": 120,
            },
            "remote-api": {
                "url": "https://api.example.com/mcp",
                "headers": {"X-API-Key": "secret-key-12345"},
            },
        }
        mcp_yaml.write_text(yaml.safe_dump(config), encoding="utf-8")

        original = _make_skill_view_result(str(skill_dir))
        hook_output = create_hook()(
            tool_name=SKILL_VIEW, result=original, args={},
        )

        assert hook_output is not None and hook_output.startswith(original)
        assert all(
            bit in hook_output
            for bit in (
                "### local-db",
                "### remote-api",
                "python -m db_server",
                "url: https://api.example.com/mcp",
                "timeout: 30s",
                "connect_timeout: 5s",
                "idle_timeout: 120s",
            )
        )
        assert "secret-key-12345" not in hook_output
        assert hook_output.count("### ") == 2

    def test_fail_open_and_no_connection_import(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            json,
            "loads",
            Mock(side_effect=RuntimeError("simulated crash")),
        )

        hook_output = create_hook()(
            tool_name=SKILL_VIEW,
            result='{"ok": true, "path": "/tmp"}',
            args={},
        )

        src = Path(__file__).resolve().parents[1] / "_skill_view_hook.py"
        source_text = src.read_text(encoding="utf-8")  # noqa: WPS226

        assert hook_output is None
        assert "from _connection import" not in source_text
        assert "import _connection" not in source_text
        assert "SkillMcpManager" not in source_text
