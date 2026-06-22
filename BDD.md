# hermes-skill-mcp — BDD Specification v2

> **Reviewed**: Oracle (gpt-5.5) + manual Hermes API verification  
> **Changes from v1**: toolset `"skill-mcp"`, `skill_name` parameter, `transform_tool_result` hook, async handler, 55 scenarios

## Purpose

Hermes plugin. Skills carry MCP servers via `mcp.yaml` sidecar.  
Agent calls `skill_mcp(skill_name, mcp_name, tool_name, arguments)`.  
No `config.yaml` editing. No restart. One tool in schema.

## Scope

| In scope | Out of scope |
|----------|-------------|
| `skill_mcp` tool in `"skill-mcp"` toolset | Modifying Hermes core |
| MCP config from `mcp.yaml` in skill dir | Parsing `mcp:` from SKILL.md frontmatter (phase 2) |
| Stdio + HTTP/StreamableHTTP transport | SSE transport |
| Lazy connect on first call | Pre-connect on skill load |
| Idle cleanup (5 min timeout) | Per-user isolation in gateway (phase 2) |
| `transform_tool_result` hook for `skill_view` augmentation | Full tool schema injection into agent context |
| `async def` handler (`is_async=True`) | OAuth flow (phase 2) |
| Static MCP list in `skill_view` (no handshake) | `hermes mcp` CLI integration (phase 2) |
| `resource_name` / `prompt_name` parameters | — |

---

## Feature 1: Plugin Discovery & Registration

### Scenario 1.1: Plugin loads and registers tool
**Given** Hermes starts with `~/.hermes/plugins/skill-mcp/` present  
**And** `plugin.yaml` declares `name: skill-mcp, kind: standalone`  
**And** Python `mcp` package installed  
**When** Hermes discovers plugins  
**Then** `register(ctx)` is called  
**And** `ctx.register_tool("skill_mcp", toolset="skill-mcp", is_async=True, ...)` registers one tool  
**And** log: `"skill-mcp: registered skill_mcp tool in toolset skill-mcp"`  

### Scenario 1.2: Plugin toolset hidden when MCP SDK missing
**Given** Python `mcp` package NOT installed  
**When** `register(ctx)` is called  
**Then** `check_fn` returns `False`  
**And** tool `skill_mcp` registered but toolset `"skill-mcp"` unavailable to agent  
**And** log: `"skill-mcp: MCP SDK not available, skill-mcp toolset disabled"`  
**And** no crash, no ImportError  

### Scenario 1.3: Plugin registers `transform_tool_result` hook
**Given** plugin loads successfully  
**When** `register(ctx)` is called  
**Then** `ctx.register_hook("transform_tool_result", augment_skill_view_with_mcp)` is called  
**And** no other hooks or middleware registered  

---

## Feature 2: MCP Config Discovery

### Scenario 2.1: `mcp.yaml` present and valid
**Given** `~/.hermes/skills/sqlite-workflow/mcp.yaml`:
```yaml
sqlite:
  command: "uvx"
  args: ["mcp-server-sqlite"]
  timeout: 30
```
**When** skill is loaded  
**Then** plugin reads and parses `mcp.yaml`  
**And** server `"sqlite"` available for `skill_mcp(skill_name="sqlite-workflow", mcp_name="sqlite", ...)`  

### Scenario 2.2: HTTP transport
**Given** `mcp.yaml`:
```yaml
company_api:
  url: "https://mcp.company.com/v1"
  headers:
    Authorization: "Bearer ${COMPANY_API_KEY}"
```
**When** config parsed  
**Then** `${COMPANY_API_KEY}` expanded from process env  
**And** transport type detected as HTTP  

### Scenario 2.3: Multiple servers
**Given** `mcp.yaml` with `sqlite` + `github` entries  
**When** config parsed  
**Then** both available as `mcp_name` values under same `skill_name`  

### Scenario 2.4: Duplicate server names in one file — rejected
**Given** `mcp.yaml`:
```yaml
sqlite:
  command: "uvx"
  args: ["mcp-server-sqlite"]
sqlite:
  command: "npx"
  args: ["other-server"]
```
**When** config parsed  
**Then** warning logged: `"skill-mcp: duplicate server name 'sqlite' in <path>"`  
**And** second entry ignored  

### Scenario 2.5: Duplicate `mcp_name` across skills — resolved by `skill_name`
**Given** skill `"skill-a"` has `mcp_name="shared"`, skill `"skill-b"` also has `mcp_name="shared"`  
**When** agent calls `skill_mcp(skill_name="skill-a", mcp_name="shared", ...)`  
**Then** plugin resolves to `skill-a`'s config only  
**And** agent calls `skill_mcp(skill_name="skill-b", mcp_name="shared", ...)`  
**Then** plugin resolves to `skill-b`'s config  

### Scenario 2.6: No `mcp.yaml` — silent skip
**Given** skill has `SKILL.md` but no `mcp.yaml`  
**When** skill loaded  
**Then** no MCP servers registered  
**And** no error/warning  

### Scenario 2.7: Invalid YAML
**Given** `mcp.yaml` is not valid YAML  
**When** plugin parses  
**Then** warning: `"skill-mcp: failed to parse mcp.yaml in <path>: <error>"`  
**And** no MCP servers for this skill  
**And** skill loads normally  

### Scenario 2.8: Unknown fields — forward compatible
**Given** `mcp.yaml` has `sampling: {enabled: true}` field  
**When** config parsed  
**Then** unknown field silently ignored  
**And** server connects with known fields only  

### Scenario 2.9: Empty `mcp.yaml`
**Given** `mcp.yaml` has no server entries  
**When** config parsed  
**Then** no servers registered  
**And** no error  

### Scenario 2.10: Relative paths resolve to `mcp.yaml` directory
**Given** `mcp.yaml` at `~/.hermes/skills/tool/`:
```yaml
local:
  command: "python"
  args: ["./server.py"]
```
**When** config parsed  
**Then** `args` resolved relative to `~/.hermes/skills/tool/`  
**And** effective command: `python ~/.hermes/skills/tool/server.py`  

### Scenario 2.11: Path escaping skill dir — rejected
**Given** `mcp.yaml`:
```yaml
escape:
  command: "python"
  args: ["../../../etc/passwd"]
```
**When** resolved path escapes `~/.hermes/skills/`  
**Then** server entry rejected  
**And** warning logged  

### Scenario 2.12: Max servers per skill
**Given** `mcp.yaml` has 33 server entries  
**When** config parsed  
**Then** warning: `"skill-mcp: too many MCP servers (33), max 32. Truncated."`  
**And** first 32 entries loaded  

### Scenario 2.13: `mcp.json` with `mcpServers` wrapper (Claude Code format)
**Given** `~/.hermes/skills/sqlite-workflow/mcp.json`:
```json
{
  "mcpServers": {
    "sqlite": {
      "command": "uvx",
      "args": ["mcp-server-sqlite"]
    }
  }
}
```
**When** skill is loaded  
**Then** plugin reads `mcp.json`  
**And** server `"sqlite"` available for `skill_mcp(skill_name="sqlite-workflow", mcp_name="sqlite", ...)`  

### Scenario 2.14: `mcp.json` flat format (auto-detect)
**Given** `~/.hermes/skills/sqlite-workflow/mcp.json`:
```json
{
  "sqlite": {
    "command": "uvx",
    "args": ["mcp-server-sqlite"]
  }
}
```
**When** skill is loaded  
**Then** plugin detects flat format (no `mcpServers` key, values have `command`)  
**And** server `"sqlite"` available  

### Scenario 2.15: `mcp.json` takes priority over `mcp.yaml`
**Given** skill has both `mcp.json` and `mcp.yaml`  
**When** skill is loaded  
**Then** `mcp.json` parsed  
**And** `mcp.yaml` ignored  

### Scenario 2.16: `mcp.yaml` fallback when no `mcp.json`
**Given** skill has `mcp.yaml` but no `mcp.json`  
**When** skill is loaded  
**Then** `mcp.yaml` parsed as before  
**And** backward compatibility preserved  

### Scenario 2.17: `mcp.json` with explicit `type` field
**Given** `mcp.json`:
```json
{
  "mcpServers": {
    "api": {
      "type": "http",
      "url": "https://mcp.example.com/v1"
    }
  }
}
```
**When** config parsed  
**Then** transport type detected as HTTP from explicit `type` field  

### Scenario 2.18: `mcp.json` with `cwd` field
**Given** `mcp.json`:
```json
{
  "mcpServers": {
    "lsp": {
      "command": "node",
      "args": ["./server.js"],
      "cwd": "."
    }
  }
}
```
**When** config parsed  
**Then** `cwd` resolved relative to `mcp.json` directory  

### Scenario 2.19: Invalid `mcp.json`
**Given** `mcp.json` is not valid JSON  
**When** plugin parses  
**Then** warning: `"skill-mcp: failed to parse mcp.json in <path>: <error>"`  
**And** no MCP servers for this skill  
**And** skill loads normally  

### Scenario 2.20: `mcp.json` with no recognizable servers
**Given** `mcp.json`: `{"foo": "bar"}`  
**When** config parsed  
**Then** no `mcpServers` key and no values with `command`/`url`  
**And** returns `{}`  
**And** warning logged  

### Scenario 2.21: MCP config in SKILL.md frontmatter
**Given** `~/.hermes/skills/sqlite-workflow/SKILL.md`:
```yaml
---
name: sqlite-workflow
description: SQLite workflow skill
mcp:
  sqlite:
    command: uvx
    args: [mcp-server-sqlite]
---
Skill body.
```
**And** no `mcp.json` or `mcp.yaml` in skill dir  
**When** skill is loaded  
**Then** plugin parses `mcp:` key from frontmatter  
**And** server `"sqlite"` available  

### Scenario 2.22: Frontmatter MCP with HTTP transport
**Given** `SKILL.md` frontmatter:
```yaml
---
name: api-skill
mcp:
  company_api:
    url: "https://mcp.company.com/v1"
    headers:
      Authorization: "Bearer ${COMPANY_API_KEY}"
---
```
**When** config parsed  
**Then** `${COMPANY_API_KEY}` expanded from env  
**And** transport type detected as HTTP  

### Scenario 2.23: Frontmatter MCP priority — below mcp.json
**Given** skill has `mcp.json` with server `"from-json"`  
**And** `SKILL.md` frontmatter with `mcp:` containing server `"from-frontmatter"`  
**When** skill is loaded  
**Then** `mcp.json` parsed  
**And** server `"from-json"` available  
**And** server `"from-frontmatter"` NOT available  

### Scenario 2.24: Frontmatter MCP priority — above mcp.yaml
**Given** skill has `SKILL.md` frontmatter with `mcp:` containing server `"from-frontmatter"`  
**And** `mcp.yaml` with server `"from-yaml"`  
**And** no `mcp.json`  
**When** skill is loaded  
**Then** frontmatter parsed  
**And** server `"from-frontmatter"` available  
**And** server `"from-yaml"` NOT available  

### Scenario 2.25: SKILL.md without `mcp:` key — fallback to mcp.yaml
**Given** `SKILL.md` frontmatter without `mcp:` key  
**And** `mcp.yaml` with server `"sqlite"`  
**And** no `mcp.json`  
**When** skill is loaded  
**Then** `mcp.yaml` parsed (frontmatter has no `mcp:` key)  

### Scenario 2.26: SKILL.md without frontmatter — no MCP from frontmatter
**Given** `SKILL.md` starts with `# My Skill` (no `---` frontmatter)  
**And** no `mcp.json`, no `mcp.yaml`  
**When** skill is loaded  
**Then** no MCP servers from frontmatter  
**And** no error  

### Scenario 2.27: Malformed YAML in frontmatter
**Given** `SKILL.md` frontmatter has invalid YAML  
**When** plugin parses  
**Then** warning: `"skill-mcp: failed to parse frontmatter in <path>: <error>"`  
**And** no MCP servers from frontmatter  
**And** skill loads normally  

### Scenario 2.28: `mcp:` value not a dict
**Given** `SKILL.md` frontmatter:
```yaml
---
name: bad-skill
mcp: "not a dict"
---
```
**When** plugin parses  
**Then** warning logged  
**And** no MCP servers from frontmatter  

### Scenario 2.29: SSE transport in config
**Given** `mcp.json`:
```json
{
  "mcpServers": {
    "remote-sse": {
      "type": "sse",
      "url": "https://mcp.example.com/sse",
      "headers": {
        "Authorization": "Bearer ${API_KEY}"
      }
    }
  }
}
```
**When** config parsed  
**Then** `${API_KEY}` expanded from env  
**And** transport type detected as SSE  

### Scenario 2.30: SSE type with command — rejected
**Given** config has `type: "sse"` AND `command: "some-cmd"`  
**When** config parsed  
**Then** server entry rejected  
**And** warning: `"skill-mcp: server 'X' has type 'sse' but includes command — skipped"`  

### Scenario 2.31: SSE type without url — rejected
**Given** config has `type: "sse"` but no `url`  
**When** config parsed  
**Then** server entry rejected  
**And** warning: `"skill-mcp: server 'X' has type 'sse' but no url — skipped"`  
---

## Feature 3: `skill_mcp` Tool — Happy Path

### Scenario 3.1: First call — lazy connect + execute
**Given** skill `"sqlite-workflow"` loaded with `mcp.yaml` (server `"sqlite"`, command `uvx mcp-server-sqlite`)  
**And** `uvx mcp-server-sqlite` on PATH  
**When** agent calls `skill_mcp(skill_name="sqlite-workflow", mcp_name="sqlite", tool_name="query", arguments={"sql":"SELECT 1"})`  
**Then** plugin spawns `uvx mcp-server-sqlite` via MCP stdio  
**And** MCP initialize handshake (protocol version from `mcp` SDK)  
**And** `tools/call` invoked with `name="query"`, `arguments={"sql":"SELECT 1"}`  
**And** result returned: `{"ok": true, "data": [{"1":1}]}`  
**And** connection cached with key `{session_id}:{skill_name}:{mcp_name}`  

### Scenario 3.2: Subsequent call — cache reuse
**Given** `skill_mcp(skill_name="sqlite-workflow", mcp_name="sqlite", ...)` already called  
**When** same `(skill_name, mcp_name)` called again  
**Then** cached connection reused  
**And** no new subprocess spawned  

### Scenario 3.3: HTTP transport
**Given** `mcp.yaml` has `url: "https://mcp.example.com/v1"`  
**When** `skill_mcp(skill_name="remote-skill", mcp_name="api", tool_name="ping")`  
**Then** HTTP/StreamableHTTP transport used  
**And** headers from `mcp.yaml` sent  

### Scenario 3.4: Resource read
**Given** MCP server has resource `"docs://readme"`  
**When** `skill_mcp(..., resource_name="docs://readme")`  
**Then** `resources/read` invoked with `uri="docs://readme"`  

### Scenario 3.5: Prompt get
**Given** MCP server has prompt `"summarize"`  
**When** `skill_mcp(..., prompt_name="summarize", arguments={"text":"..."})`  
**Then** `prompts/get` invoked with `name="summarize"`  

### Scenario 3.6: `arguments` as JSON object (primary format)
**Given** `arguments` parameter is `{"sql": "SELECT 1"}` (parsed dict)  
**When** tool executes  
**Then** dict used directly  

### Scenario 3.7: SSE transport
**Given** `mcp.json` has server with `type: "sse"`, `url: "https://mcp.example.com/sse"`  
**When** `skill_mcp(skill_name="remote-skill", mcp_name="sse-server", tool_name="ping")`  
**Then** SSE transport used (not HTTP/StreamableHTTP)  
**And** headers from config sent  
**And** SSE connection cached with key `{session_id}:{skill_name}:{mcp_name}`  
---

## Feature 4: `skill_mcp` Tool — Error Cases

### Scenario 4.1: `skill_name` not found
**When** `skill_mcp(skill_name="nonexistent", ...)`  
**Then** error:
```json
{"ok": false, "error_code": "SKILL_NOT_FOUND", "message": "Skill 'nonexistent' not loaded.", "retryable": false}
```

### Scenario 4.2: `mcp_name` not in skill config
**When** `skill_mcp(skill_name="sqlite-workflow", mcp_name="unknown", ...)`  
**Then** error:
```json
{"ok": false, "error_code": "MCP_NOT_FOUND", "message": "MCP server 'unknown' not found in skill 'sqlite-workflow'. Available: sqlite", "retryable": false}
```

### Scenario 4.3: Skill has no `mcp.yaml`
**When** `skill_mcp(skill_name="basic-skill", mcp_name="any", ...)` where `basic-skill` has no `mcp.yaml`  
**Then** error:
```json
{"ok": false, "error_code": "NO_MCP_CONFIG", "message": "Skill 'basic-skill' has no MCP servers configured.", "retryable": false}
```

### Scenario 4.4: MCP SDK not installed
**Given** `mcp` package not installed  
**When** `skill_mcp(...)` called  
**Then** error:
```json
{"ok": false, "error_code": "MCP_SDK_MISSING", "message": "MCP SDK not installed. Run: pip install mcp", "retryable": false}
```

### Scenario 4.5: Command not on PATH
**Given** `command: "nonexistent-binary"`  
**When** `skill_mcp(...)`  
**Then** error:
```json
{"ok": false, "error_code": "MCP_CONNECT_FAILED", "message": "Failed to connect to MCP server 'X': [Errno 2] No such file or directory: 'nonexistent-binary'. Hints: Ensure command installed and on PATH.", "retryable": true}
```

### Scenario 4.6: Connect timeout
**Given** `connect_timeout: 10` in `mcp.yaml`, server unresponsive  
**When** `skill_mcp(...)`  
**Then** after 10s:
```json
{"ok": false, "error_code": "MCP_CONNECT_TIMEOUT", "message": "Connection timed out after 10s for MCP server 'X'.", "retryable": true}
```

### Scenario 4.7: Tool call timeout
**Given** `timeout: 5` in `mcp.yaml`, tool takes >5s  
**When** `skill_mcp(...)`  
**Then** after 5s:
```json
{"ok": false, "error_code": "MCP_TOOL_TIMEOUT", "message": "Tool 'X' timed out after 5s on MCP server 'Y'.", "retryable": true}
```

### Scenario 4.8: `tool_name` not on server
**When** `skill_mcp(..., tool_name="nonexistent")`  
**Then** error from MCP server:
```json
{"ok": false, "error_code": "MCP_TOOL_NOT_FOUND", "message": "Tool 'nonexistent' not found on MCP server 'X'.", "retryable": false}
```

### Scenario 4.9: MCP tool execution error
**When** tool fails with `"no such table: users"`  
**Then**:
```json
{"ok": false, "error_code": "MCP_TOOL_ERROR", "message": "no such table: users", "retryable": false}
```
**And** connection stays alive  

### Scenario 4.10: MCP process crash mid-call
**Given** MCP stdio process exits during tool execution  
**When** `skill_mcp(...)`  
**Then**:
```json
{"ok": false, "error_code": "MCP_SERVER_EXITED", "message": "MCP server 'X' exited with code 1. stderr: ...", "retryable": true}
```
**And** cache entry invalidated  
**And** next call spawns fresh process  

### Scenario 4.11: Unsupported MCP protocol version
**Given** MCP server reports protocol version > SDK supports  
**When** handshake  
**Then**:
```json
{"ok": false, "error_code": "MCP_UNSUPPORTED_PROTOCOL", "message": "MCP server 'X' requires protocol vN, SDK supports vM.", "retryable": false}
```

### Scenario 4.12: Both `tool_name` + `resource_name` provided
**Then**:
```json
{"ok": false, "error_code": "INVALID_ARGS", "message": "Exactly one of tool_name, resource_name, or prompt_name required.", "retryable": false}
```

### Scenario 4.13: None of `tool_name`/`resource_name`/`prompt_name` provided
**Then**:
```json
{"ok": false, "error_code": "INVALID_ARGS", "message": "At least one of tool_name, resource_name, or prompt_name required.", "retryable": false}
```

### Scenario 4.14: `skill_name` parameter missing
**Then**:
```json
{"ok": false, "error_code": "INVALID_ARGS", "message": "skill_name is required.", "retryable": false}
```

### Scenario 4.15: No active session
**Given** batch runner / non-session context  
**Then**:
```json
{"ok": false, "error_code": "NO_SESSION", "message": "No active session for skill MCP call.", "retryable": false}
```

### Scenario 4.16: SSE connect failure
**Given** SSE server at unreachable URL  
**When** `skill_mcp(...)`  
**Then** error:
```json
{"ok": false, "error_code": "MCP_CONNECT_FAILED", "message": "Failed to connect to MCP server 'X': <details>", "retryable": true}
```

### Scenario 4.17: SSE type with command — rejected
**Given** config has `type: "sse"` AND `command: "some-cmd"`  
**When** config parsed  
**Then** server entry rejected  
**And** warning: `"skill-mcp: server 'X' has type 'sse' but includes command — skipped"`  

### Scenario 4.18: SSE type without url — rejected
**Given** config has `type: "sse"` but no `url`  
**When** config parsed  
**Then** server entry rejected  
**And** warning: `"skill-mcp: server 'X' has type 'sse' but no url — skipped"`  
---

## Feature 5: Connection Lifecycle

### Scenario 5.1: Lazy — no connect until first call
**Given** skill with `mcp.yaml` loaded  
**When** no `skill_mcp` call made  
**Then** zero MCP subprocesses spawned  
**And** zero network connections opened  

### Scenario 5.2: Cache key includes `session_id`
**Given** handler receives `session_id` in `**kwargs`  
**When** connection created  
**Then** cache key: `"{session_id}:{skill_name}:{mcp_name}"`  

### Scenario 5.3: Different sessions — isolated connections
**Given** session A calls `skill_mcp(skill_name="sk", mcp_name="db", ...)`  
**And** session B calls same `(skill_name, mcp_name)`  
**Then** two separate MCP processes spawned (different session_id keys)  

### Scenario 5.4: Idle cleanup — 5 min timeout
**Given** connection to `"sqlite"` cached, last used 5+ min ago  
**When** cleanup timer fires  
**Then** connection closed  
**And** subprocess terminated  
**And** next call spawns fresh process  

### Scenario 5.5: Cleanup timer — monotonic clock, safe cancel on shutdown
**Given** idle timer running  
**When** `shutdown_all()` called  
**Then** timer cancelled  
**And** no dangling `asyncio.Task` after shutdown  

### Scenario 5.6: Plugin shutdown — all connections closed
**Given** 3 active connections  
**When** `on_session_end` or process exit  
**Then** all 3 closed  
**And** subprocesses terminated (no zombies)  

### Scenario 5.7: Concurrent — different servers run in parallel
**Given** connections to `"sqlite"` and `"github"`  
**When** both called in parallel (Hermes parallel tool execution)  
**Then** both execute concurrently  
**And** results returned independently  

### Scenario 5.8: Concurrent — same server serialized
**Given** one connection to `"sqlite"`  
**When** two parallel calls to same server  
**Then** calls serialized via `asyncio.Lock`  
**And** both results correct (no corruption)  

### Scenario 5.9: MCP server not supporting tools capability
**Given** server capabilities missing `tools`  
**When** `skill_mcp` tries `list_tools` or `callTool`  
**Then**:
```json
{"ok": false, "error_code": "MCP_CAPABILITY_MISSING", "message": "MCP server 'X' does not support tools capability.", "retryable": false}
```

### Scenario 5.10: SSE idle cleanup
**Given** SSE connection cached, last used 5+ min ago  
**When** cleanup timer fires  
**Then** SSE connection closed  
**And** next call creates fresh connection  

### Scenario 5.11: SSE concurrent — same server serialized
**Given** one SSE connection to `"remote-sse"`  
**When** two parallel calls to same server  
**Then** calls serialized via `asyncio.Lock`  
**And** both results correct (no corruption)  
---

## Feature 6: `skill_view` Augmentation

### Scenario 6.1: Hook intercepts `skill_view` result
**Given** `transform_tool_result` hook registered  
**When** agent calls `skill_view(name="sqlite-workflow")`  
**Then** hook receives `tool_name="skill_view"`  
**And** hook parses result JSON, extracts skill name  
**And** if `mcp.yaml` exists → appends MCP section to result  
**And** modified result returned to agent  

### Scenario 6.2: Static MCP list — no handshake
**Given** `skill_view` augmented MCP section  
**Then** output shows:
```
## MCP Servers

### sqlite
*Static config — connect on first skill_mcp call.*

Configuration:
  command: uvx mcp-server-sqlite
  timeout: 30s

Use `skill_mcp(skill_name="sqlite-workflow", mcp_name="sqlite", tool_name="...", arguments={...})` to invoke.
```
**And** NO `listTools` handshake performed  
**And** `skill_mcp` tool descriptions not shown (unknown until first call)  

### Scenario 6.3: MCP config has multiple servers — all listed
**Given** `mcp.yaml` has `sqlite` + `github`  
**When** `skill_view`  
**Then** both listed with static config  

### Scenario 6.4: No `mcp.yaml` — no MCP section
**Given** skill has `SKILL.md` only  
**When** `skill_view`  
**Then** no "MCP Servers" section  
**And** skill content shown normally  

### Scenario 6.5: Hook handles parse failure gracefully
**Given** `skill_view` result is malformed JSON (edge case)  
**When** hook tries to parse  
**Then** result returned unmodified  
**And** debug log: `"skill-mcp: failed to parse skill_view result"`  

### Scenario 6.6: Hook ignores non-skill_view tool calls
**Given** `transform_tool_result` hook  
**When** agent calls `terminal(...)` or any non-`skill_view` tool  
**Then** hook returns `None` (no modification)  
**And** result passes through unchanged  

---

## Feature 7: Security

### Scenario 7.1: Env filtering for stdio
**Given** `mcp.yaml` has `env: {MY_TOKEN: "${MY_TOKEN}"}`  
**When** subprocess spawned  
**Then** only safe baseline vars + explicit `env` passed  
**And** `os.environ` NOT inherited wholesale  
**And** safe baseline: `PATH`, `HOME`, `USER`, `TMPDIR`, `LANG`  

### Scenario 7.2: No env expansion without `${}` syntax
**Given** `mcp.yaml` has `headers: {Authorization: "Bearer static-key"}`  
**When** HTTP connection made  
**Then** `"static-key"` used literally (no env var expansion)  

### Scenario 7.3: Credential redaction in errors
**Given** MCP server error contains `Bearer sk-abc123`  
**When** error returned to agent  
**Then** `sk-abc123` replaced with `***`  
**And** patterns covered: `sk-*`, `ghp_*`, `Bearer *`, `key=*`, `token=*`, `password=*`, `secret=*`  

### Scenario 7.4: `PATH` append-only
**Given** `mcp.yaml` has `env: {PATH: "/malicious"}`
**When** subprocess env prepared  
**Then** `PATH` appended, not replaced  
**And** warning logged  

### Scenario 7.5: Denied commands
**Given** `mcp.yaml`:
```yaml
bad:
  command: "sudo"
  args: ["rm", "-rf", "/"]
```
**When** config parsed  
**Then** server entry rejected  
**And** warning: `"skill-mcp: command 'sudo' not allowed for MCP server 'bad'"`  
**And** denylist: `sudo`, `su`, commands with `shell: true`  

### Scenario 7.6: Trust boundary same as skill installation
**Given** user installs skill with `mcp.yaml`  
**When** `hermes skills install ...`  
**Then** warning displayed if skill has MCP servers  
**And** user must confirm: `"This skill will run external commands: uvx mcp-server-sqlite. Proceed?"`  

### Scenario 7.7: No shell interpolation
**Given** `mcp.yaml` args: `["echo", "$(whoami)"]`  
**When** subprocess spawned  
**Then** args passed literally to `subprocess.Popen` (no shell)  
**And** `$(whoami)` treated as literal string, not expanded  

---

## Feature 8: Tool Schema

### Scenario 8.1: `skill_mcp` schema
**Given** tool registered in `"skill-mcp"` toolset  
**When** schema sent to model  
**Then**:

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `skill_name` | string | ✅ | Skill name as returned by `skill_view` |
| `mcp_name` | string | ✅ | MCP server name from skill's `mcp.yaml` |
| `tool_name` | string | ❌ | MCP tool to call |
| `resource_name` | string | ❌ | MCP resource URI to read |
| `prompt_name` | string | ❌ | MCP prompt to get |
| `arguments` | object | ❌ | Tool/prompt arguments as JSON object |
| `grep` | string | ❌ | Regex to filter output lines |

**And** description: `"Invoke MCP server from skill config. Requires skill_name + mcp_name + exactly one of: tool_name, resource_name, prompt_name."`  

### Scenario 8.2: Handler signature matches Hermes contract
**Given** `handler` registered as `async def handle_skill_mcp(args, **kwargs)`  
**When** Hermes dispatches `skill_mcp`  
**Then** `args` is parsed dict with keys: `skill_name`, `mcp_name`, `tool_name`, `arguments`, `grep`  
**And** `kwargs` contains: `task_id`, `session_id`, `user_task`  
**And** handler returns JSON string  

---

## Feature 9: Timeouts

### Scenario 9.1: `connect_timeout` from `mcp.yaml`
**Given** `mcp.yaml` has `connect_timeout: 15`  
**When** connecting to MCP server  
**Then** connection times out after 15s (default: 10s)  

### Scenario 9.2: `timeout` from `mcp.yaml` for tool calls
**Given** `mcp.yaml` has `timeout: 45`  
**When** `skill_mcp` tool call in progress  
**Then** call aborted after 45s (default: 60s)  

### Scenario 9.3: Idle cleanup — `idle_timeout` configurable
**Given** `mcp.yaml` has `idle_timeout: 120`  
**When** no calls to this server for 120s  
**Then** connection cleaned up (default: 300s)  

---

## Feature 10: Non-Functional

### Scenario 10.1: Parse latency <50ms for typical config
**Given** `mcp.yaml` with 3 servers  
**When** config parsed at skill load time  
**Then** parse completes <50ms  

### Scenario 10.2: First-call latency bounded by connect timeout
**Given** `mcp.yaml` has `connect_timeout: 10`  
**When** first `skill_mcp` call  
**Then** total latency = connect time + tool time, bounded by connect_timeout on failure  

### Scenario 10.3: Cached call overhead <50ms
**Given** cached connection  
**When** `skill_mcp` called  
**Then** plugin overhead (excl. MCP tool time) <50ms  

### Scenario 10.4: No memory leak over N cycles
**Given** 100 create/call/idle-cleanup cycles with mock MCP  
**When** all connections cleaned up  
**Then** subprocess count returns to baseline (±1)  
**And** file descriptor count returns to baseline (±5)  
**And** Python object count growth <10% over baseline  

### Scenario 10.5: Platform support
**Given** Hermes runs on Linux, macOS, Windows (WSL)  
**When** `skill_mcp` called  
**Then** stdio transport works on all platforms  
**And** HTTP transport works on all platforms  

---

## Feature 11: Configuration Schema (config reference)

### Config sources (priority order)

1. `mcp.json` — JSON, Claude Code compatible (`{"mcpServers": {...}}` wrapper or flat auto-detect)
2. `SKILL.md` frontmatter `mcp:` key — YAML, embedded in skill file
3. `mcp.yaml` — YAML, legacy format

### Valid fields per server entry

```yaml
server_name:
  type: "stdio|http|sse"     # transport type (optional, inferred from command/url)
  command: "string"           # stdio: executable (REQUIRED for stdio)
  args: ["string", ...]       # stdio: arguments (default: [])
  env: {KEY: "value"}         # stdio: extra env vars (default: {})
  url: "string"               # http/sse: server URL (REQUIRED for http/sse)
  headers: {Key: "value"}     # http/sse: extra headers (default: {})
  cwd: "string"               # stdio: working directory (optional, resolved relative to config)
  timeout: 60                 # per-tool-call timeout, seconds (default: 60)
  connect_timeout: 10         # connection timeout, seconds (default: 10)
  idle_timeout: 300           # idle cleanup timeout, seconds (default: 300)
```

### Transport type rules

| `type` field | `command` present | `url` present | Result |
|---|---|---|---|
| `"stdio"` | required | must NOT have | stdio |
| `"http"` | must NOT have | required | HTTP/StreamableHTTP |
| `"sse"` | must NOT have | required | SSE |
| not set | yes | no | stdio (inferred) |
| not set | no | yes | HTTP (inferred) |
| not set | yes | yes | rejected |

If `type` is omitted, transport is inferred from `command`/`url` presence.
`command` and `url` are mutually exclusive (unless `type` explicitly set).

---

## Verification Checklist

- [ ] `pip install hermes-skill-mcp` succeeds Python 3.11+
- [ ] Plugin discovered in `~/.hermes/plugins/skill-mcp/`
- [ ] `hermes tools` shows `skill-mcp` toolset (hidden when `mcp` SDK missing)
- [ ] `hermes tools enable skill-mcp` activates tool
- [ ] `skill_mcp` tool visible to agent when toolset enabled
- [ ] `skill_view` output augmented with static MCP server list
- [ ] All BDD scenarios pass against:
  - [ ] `uvx mcp-server-time` (stdio, no auth)
  - [ ] `uvx mcp-server-sqlite` (stdio, args)
  - [ ] `uvx mcp-server-git` (stdio, args)
  - [ ] HTTP/Streamable HTTP server mock
- [ ] Plugin co-exists with native Hermes MCP (`mcp_*` tools)
- [ ] End-to-end: install plugin → enable toolset → load skill → `skill_view` shows MCP → `skill_mcp` calls tool → result used
- [ ] Gateway multi-user: two sessions, same skill → isolated MCP processes
- [ ] Plugin uninstall: `rm -rf ~/.hermes/plugins/skill-mcp/` → zero traces
