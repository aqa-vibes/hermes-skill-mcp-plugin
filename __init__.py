# flake8: noqa: WPS412
"""
hermes-skill-mcp: Dynamic MCP server loading from Hermes skills.
# noqa: WPS412 — plugin entrypoint must have logic

A Hermes Agent plugin that lets skills declare their own MCP servers
via a ``mcp.yaml`` sidecar file. The plugin registers a single
``skill_mcp`` tool that connects to MCP servers on demand —
no global config.yaml editing, no agent restart, no tool schema bloat.

Quick Start:
    1. Install: ``git clone <repo> ~/.hermes/plugins/skill-mcp/``
    2. Add ``mcp.yaml`` beside any SKILL.md
    3. Agent calls ``skill_mcp(mcp_name="...",
        tool_name="...", arguments='...')``

See BDD.md for full behavior specification.
"""


from __future__ import annotations


def register(ctx):
    """Called by Hermes PluginManager at plugin discovery.

    Creates one SkillMcpManager instance. Registers:
    - skill_mcp tool in "skill-mcp" toolset
    - transform_tool_result hook

    All imports deferred — no module-level ImportError without mcp SDK.
    """
    import _config
    import _connection
    import _skill_view_hook
    import _tool_handler

    manager = _connection.SkillMcpManager()

    ctx.register_tool(
        name="skill_mcp",
        toolset="skill-mcp",
        schema=_tool_handler.SKILL_MCP_SCHEMA,
        handler=_tool_handler.create_handler(manager),
        check_fn=_config.check_mcp_sdk_available,
        is_async=True,
        emoji="\U0001f50c",
    )

    ctx.register_hook(
        "transform_tool_result",
        _skill_view_hook.create_hook(),
    )
