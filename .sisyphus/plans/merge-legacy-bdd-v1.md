# Merge Legacy BDD Code → Main (wemake-clean)

> **For agentic workers:** REQUIRED SUB-SKILL: subagent-driven-development.
> Steps use checkbox (`- [ ]`) syntax.

**Goal:** Bring back all BDD-compliant code from legacy commit `9cc7c0a` into
current `main` HEAD `9667f2f`, one module per commit, fixing wemake lint errors
iteratively. End state: all 55 BDD scenarios covered, wemake lint clean,
Docker tests pass.

**Architecture:** Git feature branch `merge/legacy-bdd` from `main`. Each
module restored from legacy, refactored to pass wemake (max-line-length=80,
max-complexity=6, full wemake-python-styleguide rules), then committed.
Legacy tests brought back with each module, adapted for current Docker structure.

**Tech Stack:** Python 3.11+, `mcp>=1.0,<2`, `pyyaml>=6.0`,
`wemake-python-styleguide>=1.0`, `pytest>=8.0`, `pytest-asyncio>=0.24`

**Wemake constraints (from pyproject.toml):**
- max-line-length = 80
- max-complexity = 6 (McCabe)
- All wemake-python-styleguide defaults (no magic numbers, max args ≤5,
  max locals ≤5, max returns ≤3, etc.)

**Git strategy:**
- Branch `merge/legacy-bdd` from `main` (`9667f2f`)
- NEVER merge legacy branch directly (different histories)
- Restore files via `git show 9cc7c0a:<path> > <path>` then refactor
- One commit per module (atomic, revertible)
- Final step: verify all Docker tests pass, then merge to `main`

---

## Dependency Chain (restore order)

```
Step 1: _config.py (expand)         — no deps
Step 2: tests/test_config.py        — test expansion
    │
Step 3: _security.py (restore)      — no deps
Step 4: tests/test_security.py      — test restore
    │
Step 5: _connection.py (expand)     — depends on _config.py, _security.py
Step 6: tests/test_connection.py    — test restore
    │
Step 7: _tool_handler.py (restore)  — depends on _config, _security, _connection
Step 8: tests/test_tool_handler.py  — test restore
    │
Step 9:  _skill_view_hook.py (expand) — depends on _config.py
Step 10: tests/test_skill_view_hook.py — test restore
    │
Step 11: __init__.py (rewrite)      — depends on all modules
Step 12: tests/test_plugin_entry.py — test restore
    │
Step 13: tests/test_hermes_api_contract.py — test restore
Step 14: tests/test_edge_cases.py   — test restore
Step 15: tests/test_e2e.py          — test restore
    │
Step 16: Final integration          — remove test_skill_mcp.py,
           full Docker suite, wemake clean check
```

---

## Step 1: Expand `_config.py`

**Files:**
- Modify: `_config.py` (currently 29 lines → target ~180 lines)
- Tests: already exists in legacy `tests/test_config.py` (will restore in Step 2)

- [ ] **1.1: Extract full legacy `_config.py`**

```bash
git show 9cc7c0a:_config.py > _config.py
```

- [ ] **1.2: Run flake8 on restored file**

```bash
.venv/bin/python -m flake8 _config.py
```

Expected: multiple wemake errors (likely: complex functions, long lines,
magic numbers, too many locals).

- [ ] **1.3: Refactor for wemake compliance**

Target interface (must remain):
```
check_mcp_sdk_available() -> bool
parse_mcp_config(skill_dir: Path) -> Optional[dict]
```

Refactoring rules:
- Split `parse_mcp_config` into sub-functions if complexity > 6
- Extract magic numbers (32 max servers, timeout defaults 60/10/300)
  to module-level constants with `_` prefix
- Any function with >5 local vars → extract helper class or split
- Keep line length ≤80 chars
- Preserve all BDD behavior: env expansion, path resolution, duplicate
  detection, forward compatibility, server cap, both `command` and `url`
  rejection, path escape rejection

- [ ] **1.4: Verify wemake passes**

```bash
.venv/bin/python -m flake8 _config.py
```

Expected: exit code 0, no output.

- [ ] **1.5: Verify existing Docker tests still pass**

```bash
./scripts/run-tests.sh
```

The 14 current tests must still pass (they import `_config.py`).

- [ ] **1.6: Commit**

```bash
git add _config.py
git commit -m "feat: restore full _config.py from legacy with wemake fixes

Brings back BDD Feature 2 coverage: env expansion, path resolution,
duplicate detection, server cap, forward compatibility, command+url
mutual exclusion, path escape rejection, transport detection.
Refactored to pass max-complexity=6 and wemake-python-styleguide."
```

---

## Step 2: Restore `tests/test_config.py`

**Files:**
- Create: `tests/test_config.py` (from legacy, ~575 lines)
- Note: existing `test_skill_mcp.py` has overlapping config tests
  (`TestMcpConfigParsing`) — keep both initially, deduplicate in Step 16

- [ ] **2.1: Extract legacy test file**

```bash
git show 9cc7c0a:tests/test_config.py > tests/test_config.py
```

- [ ] **2.2: Adapt imports for Docker environment**

Legacy tests may use local imports. Adapt:
- Replace relative imports with absolute paths matching Docker layout
- Verify `conftest.py` fixtures match test expectations
- Verify `constants.py` paths match `/opt/hermes/...` structure

- [ ] **2.3: Run flake8 on test file**

```bash
.venv/bin/python -m flake8 tests/test_config.py
```

Fix wemake errors. Tests have relaxed rules but must pass flake8.

- [ ] **2.4: Run config tests in Docker**

```bash
./scripts/run-tests.sh
```

Expected: new config tests pass alongside existing tests.

- [ ] **2.5: Commit**

```bash
git add tests/test_config.py
git commit -m "test: restore test_config.py from legacy

Covers BDD F2 scenarios: valid config, HTTP transport, multiple servers,
duplicates, env expansion, path resolution, escape, server cap,
invalid YAML, empty config, forward compatibility, missing fields."
```

---

## Step 3: Restore `_security.py`

**Files:**
- Create: `_security.py` (from legacy, ~128 lines — already clean)
- This file was deleted in refactor, now fully restored

- [ ] **3.1: Extract legacy file**

```bash
git show 9cc7c0a:_security.py > _security.py
```

- [ ] **3.2: Run flake8, fix if needed**

```bash
.venv/bin/python -m flake8 _security.py
```

Legacy `_security.py` looks well-structured. Fix any violations.

- [ ] **3.3: Runtime QA — verify security functions**

```bash
.venv/bin/python -c "
import os;
from _security import filter_mcp_environment, redact_credentials, is_command_allowed;
# env filtering: safe vars inherited, secrets excluded
os.environ['SECRET_TOKEN'] = 'leak-me';
result = filter_mcp_environment({'MY_VAR': 'val'});
assert 'PATH' in result, 'PATH missing';
assert 'SECRET_TOKEN' not in result, 'secret leaked';
assert result['MY_VAR'] == 'val';
# redaction: Bearer, sk-*, ghp_*, key=, token=, password=, secret=
assert redact_credentials('Bearer sk-abc123') == 'Bearer ***';
assert redact_credentials('token=ghp_xxxx') == 'token=***';
assert redact_credentials('key=sec password=h') == 'key=*** password=***';
# denylist: sudo/su blocked
assert not is_command_allowed('sudo');
assert not is_command_allowed('su');
assert is_command_allowed('python3');
print('OK: all security checks pass');
"
```

Expected: `OK: all security checks pass`.

- [ ] **3.4: Commit**

```bash
git add _security.py
git commit -m "feat: restore _security.py from legacy

BDD Feature 7: env filtering, credential redaction (sk-*, ghp_*,
Bearer, key=*, token=*, password=*, secret=*), command denylist."
```

---

## Step 4: Restore `tests/test_security.py`

**Files:**
- Create: `tests/test_security.py` (from legacy, ~316 lines)

- [ ] **4.1: Extract legacy file**

```bash
git show 9cc7c0a:tests/test_security.py > tests/test_security.py
```

- [ ] **4.2: Adapt imports for Docker environment**

Legacy `test_security.py` imports `_security` module directly.
No path changes needed — `_security.py` has no internal imports.

- [ ] **4.3: Run flake8**

```bash
.venv/bin/python -m flake8 tests/test_security.py
```
Expected: exit 0.

- [ ] **4.4: Run in Docker — verify pass**

```bash
./scripts/run-tests.sh
```
Expected: all prior tests pass + test_security.py tests pass.
BDD F7 coverage: 7.1 (env filter), 7.2 (no-env-expansion),
7.3 (credential redaction), 7.4 (PATH append),
7.5 (denylist), 7.6 (trust boundary), 7.7 (no shell).

- [ ] **4.5: Commit**

```bash
git add tests/test_security.py
git commit -m "test: restore test_security.py from legacy

Covers BDD F7: env filtering, credential redaction,
PATH append-only, denied commands, no shell interpolation."
```

---

## Step 5: Expand `_connection.py`

**Files:**
- Modify: `_connection.py` (currently 135 lines → target ~300 lines)
- This is the most complex module. Legacy had full session-aware cache,
  idle cleanup, HTTP transport, concurrent locking.

**Legacy features missing in current:**
- Session-aware cache key (`{session_id}:{skill_name}:{mcp_name}`)
- HTTP/StreamableHTTP transport
- Idle cleanup with configurable timeout
- Concurrent lock (asyncio.Lock per connection)
- `shutdown_all()` for cleanup
- Resource/prompt calls
- MCP capability checking
- Connection timeout, tool timeout
- Process crash recovery (invalidate cache on exit)

- [ ] **5.1: Extract full legacy**

```bash
git show 9cc7c0a:_connection.py > _connection.py
```

- [ ] **5.2: Run flake8, catalog errors**

```bash
.venv/bin/python -m flake8 _connection.py
```

Expected: many complexity/local/argument violations. Legacy
`SkillMcpManager` likely has functions exceeding max-complexity=6.

- [ ] **5.3: Refactor for wemake**

Key refactoring targets:
- Extract `_connect_stdio`, `_connect_http` as separate functions
- Extract timeout handling to `_with_timeout` helper
- Extract idle cleanup to `_IdleCleanupScheduler` class
- Extract connection creation to `_create_client` factory
- Ensure `get_or_create_client` complexity ≤6
- Ensure `call_tool` complexity ≤6
- Move magic numbers to module constants:
  `_DEFAULT_IDLE_TIMEOUT = 300`, `_DEFAULT_CONNECT_TIMEOUT = 10`,
  `_DEFAULT_TOOL_TIMEOUT = 60`
- Keep all BDD behavior intact

- [ ] **5.4: Verify wemake passes**

```bash
.venv/bin/python -m flake8 _connection.py
```

- [ ] **5.5: Verify Docker tests pass**

```bash
./scripts/run-tests.sh
```

Existing connection tests (`TestMcpConnection`) must still pass.

- [ ] **5.6: Commit**

```bash
git add _connection.py
git commit -m "feat: expand _connection.py with session-aware cache

Brings back BDD Features 3,5: session-scoped cache keys,
HTTP transport, idle cleanup, concurrent locking, resource/prompt
calls, capability checking, timeouts, crash recovery.
Refactored to max-complexity=6."
```

---

## Step 6: Restore `tests/test_connection.py`

**Files:**
- Create: `tests/test_connection.py` (from legacy, ~398 lines)
- Note: overlaps with current `TestMcpConnection` in `test_skill_mcp.py`

- [ ] **6.1: Extract legacy test file**

```bash
git show 9cc7c0a:tests/test_connection.py > tests/test_connection.py
```

- [ ] **6.2: Adapt imports**

Legacy imports `from _connection import SkillMcpManager`.
Docker copies all `*.py` to `/opt/hermes/plugins/skill-mcp/` — no change needed.

- [ ] **6.3: Run flake8**

```bash
.venv/bin/python -m flake8 tests/test_connection.py
```
Expected: exit 0. Fix any violations.

- [ ] **6.4: Run in Docker**

```bash
./scripts/run-tests.sh
```
Expected: all prior tests + test_connection.py pass.
BDD F3/F5 coverage: 3.1-3.6 (happy path), 5.1-5.9 (lifecycle).

- [ ] **6.5: Commit**

```bash
git add tests/test_connection.py
git commit -m "test: restore test_connection.py from legacy

Covers BDD F3 (happy path: lazy connect, HTTP, resources,
prompts, args) and F5 (session keys, isolation, idle
cleanup, shutdown, concurrency, locking, capability)."
```

---

## Step 7: Restore `_tool_handler.py`

**Files:**
- Create: `_tool_handler.py` (from legacy, ~400 lines)
- This is the biggest refactoring challenge: legacy has complex async handler

**Legacy contents:**
- `SKILL_MCP_SCHEMA` dict (Feature 8)
- `McpError` exception hierarchy (5 classes)
- `create_handler(manager, skill_dirs)` → `async handler(args, **kwargs) -> str`
- Internal helpers: `_validate_args`, `_find_skill_dir`, `_build_error`,
  `_handle_skill_mcp` (the main orchestrator, likely >6 complexity)

- [ ] **7.1: Extract legacy**

```bash
git show 9cc7c0a:_tool_handler.py > _tool_handler.py
```

- [ ] **7.2: Run flake8**

Expected: `_handle_skill_mcp` will have max-complexity violation
(it orchestrates validation, skill lookup, config resolution,
error mapping — easily >15 complexity).

- [ ] **7.3: Refactor for wemake**

Split `_handle_skill_mcp` into pipeline stages, each ≤6 complexity:

```python
async def _handle_skill_mcp(args, manager, skill_dirs, **kwargs) -> str:
    err = _validate_and_extract(args)
    if isinstance(err, str): return err

    skill_name, mcp_name, operation = err  # (name, mcp, op_dict)

    err = _check_prerequisites(skill_name, skill_dirs)
    if err: return err

    config, err = _resolve_config(skill_name, mcp_name, skill_dirs)
    if err: return err

    session_id = kwargs.get("session_id", "default")
    if not session_id:
        return _build_error("NO_SESSION", ...)

    return await _execute_operation(
        manager, session_id, skill_name, mcp_name, config, operation
    )
```

Each helper function ≤6 complexity.

Move exception classes to `_exceptions.py` if `_tool_handler.py` gets
too large (module member count wemake rule).

- [ ] **7.4: Verify wemake passes**

```bash
.venv/bin/python -m flake8 _tool_handler.py
```

- [ ] **7.5: Commit**

```bash
git add _tool_handler.py
git commit -m "feat: restore _tool_handler.py from legacy

BDD Features 3,4,8: skill_mcp async handler, error envelope mapping
(15 error codes), tool schema, argument validation, skill lookup,
config resolution. Refactored to max-complexity=6 via pipeline pattern."
```

---

## Step 8: Restore `tests/test_tool_handler.py`

**Files:**
- Create: `tests/test_tool_handler.py` (from legacy, ~983 lines — largest file)

- [ ] **8.1: Extract legacy file**

```bash
git show 9cc7c0a:tests/test_tool_handler.py > tests/test_tool_handler.py
```

- [ ] **8.2: Run flake8**

```bash
.venv/bin/python -m flake8 tests/test_tool_handler.py
```
If WPS202 (too many members): split into:
- `tests/test_tool_handler_happy.py` — BDD F3 happy path
- `tests/test_tool_handler_errors.py` — BDD F4 error cases
Expected: exit 0 after fixes or split.

- [ ] **8.3: Adapt for refactored module interfaces**

Verify test imports match current modules:
- `from _tool_handler import SKILL_MCP_SCHEMA, create_handler, _build_error`
- `from _config import check_mcp_sdk_available, parse_mcp_config`
- `from _security import redact_credentials`
Update any renamed function references.

- [ ] **8.4: Run in Docker**

```bash
./scripts/run-tests.sh
```
Expected: all tests pass.
BDD F3/F4/F8 coverage: 3.1-3.6, 4.1-4.15, 8.1-8.2.

- [ ] **8.5: Commit**

```bash
git add tests/test_tool_handler.py  # or test_tool_handler_*.py
git commit -m "test: restore test_tool_handler.py from legacy

Covers BDD F3 (happy path), F4 (15 error scenarios),
F8 (tool schema + handler signature)."
```

---

## Step 9: Expand `_skill_view_hook.py`

**Files:**
- Modify: `_skill_view_hook.py` (currently 41 lines → target ~120 lines)

**Legacy additions needed:**
- Real `create_hook()` factory returning `transform_tool_result` handler
- JSON parse guard with debug log on failure
- `tool_name="skill_view"` check (pass-through for non-skill_view)
- Static config formatting matching BDD 6.2 output

- [ ] **9.1: Extract legacy**

```bash
git show 9cc7c0a:_skill_view_hook.py > _skill_view_hook.py
```

- [ ] **9.2: Flake8, refactor if needed, verify wemake, commit**

---

## Step 10: Restore `tests/test_skill_view_hook.py`

**Files:**
- Create: `tests/test_skill_view_hook.py` (from legacy, ~780 lines)

- [ ] **10.1: Extract legacy file**

```bash
git show 9cc7c0a:tests/test_skill_view_hook.py > tests/test_skill_view_hook.py
```

- [ ] **10.2: Run flake8**

```bash
.venv/bin/python -m flake8 tests/test_skill_view_hook.py
```
If WPS202: split into:
- `tests/test_skill_view_hook_render.py` (formatting tests)
- `tests/test_skill_view_hook_hook.py` (transform_tool_result behavior)
Expected: exit 0.

- [ ] **10.3: Run in Docker**

```bash
./scripts/run-tests.sh
```
Expected: all tests pass.
BDD F6 coverage: 6.1-6.6.

- [ ] **10.4: Commit**

```bash
git add tests/test_skill_view_hook.py  # or test_skill_view_hook_*.py
git commit -m "test: restore test_skill_view_hook.py from legacy

Covers BDD F6: hook intercept, static MCP list,
multiple servers, no mcp.yaml, parse failure,
non-skill_view pass-through."
```

---

## Step 11: Rewrite `__init__.py`

**Files:**
- Modify: `__init__.py` (currently empty → ~50 lines)

- [ ] **11.1: Write `register(ctx)` from legacy**

```bash
git show 9cc7c0a:__init__.py > __init__.py
```

- [ ] **11.2: Adapt for current module structure**

Ensure imports match refactored module interfaces. Legacy had:
```python
from ._config import check_mcp_sdk_available
from ._connection import SkillMcpManager
from ._tool_handler import SKILL_MCP_SCHEMA, create_handler
from ._skill_view_hook import create_hook
```

If any were renamed/split during refactoring, update here.

- [ ] **11.3: Flake8, verify wemake, commit**

```bash
git add __init__.py
git commit -m "feat: restore plugin entrypoint with register(ctx)

BDD Feature 1: register_tool('skill_mcp', toolset='skill-mcp',
is_async=True), register_hook('transform_tool_result'),
check_fn=gated by MCP SDK availability."
```

---

## Step 12: Restore `tests/test_plugin_entry.py`

- [ ] **12.1: Extract legacy file**

```bash
git show 9cc7c0a:tests/test_plugin_entry.py > tests/test_plugin_entry.py
```

- [ ] **12.2: Adapt imports**

Verify test imports `register` from `__init__`.
If function signature changed, update test expectations.

- [ ] **12.3: Run flake8**

```bash
.venv/bin/python -m flake8 tests/test_plugin_entry.py
```
Expected: exit 0.

- [ ] **12.4: Run in Docker**

```bash
./scripts/run-tests.sh
```
Expected: all tests pass.
BDD F1 coverage: 1.1 (plugin registers tool),
1.2 (SDK missing gate), 1.3 (hook registration).

- [ ] **12.5: Commit**

```bash
git add tests/test_plugin_entry.py
git commit -m "test: restore test_plugin_entry.py from legacy

Covers BDD F1: plugin discovery, SDK-missing gate,
hook registration."
```

---

## Step 13: Restore `tests/test_hermes_api_contract.py`

- [ ] **13.1: Extract legacy file**

```bash
git show 9cc7c0a:tests/test_hermes_api_contract.py > tests/test_hermes_api_contract.py
```

- [ ] **13.2: Run flake8, verify Docker**

```bash
.venv/bin/python -m flake8 tests/test_hermes_api_contract.py
./scripts/run-tests.sh
```
Expected: flake8 exit 0, Docker tests pass.
BDD F1 + F8.2: verifies handler signature matches Hermes contract.

- [ ] **13.3: Commit**

```bash
git add tests/test_hermes_api_contract.py
git commit -m "test: restore test_hermes_api_contract.py from legacy

Verifies Hermes plugin API contract: register_tool signature,
handler args/kwargs, async dispatch, return format."
```

---

## Step 14: Restore `tests/test_edge_cases.py`

- [ ] **14.1: Extract legacy file**

```bash
git show 9cc7c0a:tests/test_edge_cases.py > tests/test_edge_cases.py
```

- [ ] **14.2: Run flake8, verify Docker**

```bash
.venv/bin/python -m flake8 tests/test_edge_cases.py
./scripts/run-tests.sh
```
Expected: flake8 exit 0, Docker tests pass.
BDD F4/F5 edge: concurrency, crash recovery, protocol mismatch.

- [ ] **14.3: Commit**

```bash
git add tests/test_edge_cases.py
git commit -m "test: restore test_edge_cases.py from legacy

Covers BDD F4/F5 edge: concurrency, crash recovery,
protocol mismatch, arg validation edge cases."
```

---

## Step 15: Restore `tests/test_e2e.py`

- [ ] **15.1: Extract legacy file**

```bash
git show 9cc7c0a:tests/test_e2e.py > tests/test_e2e.py
```

- [ ] **15.2: Run flake8**

```bash
.venv/bin/python -m flake8 tests/test_e2e.py
```
Expected: exit 0.

- [ ] **15.3: E2E runtime note**

Requires `HERMES_API_KEY` in Docker env. Skips without it — acceptable.
With key: verifies full pipeline install → load → skill_view →
skill_mcp call → result used. BDD F1-F6 integration.

- [ ] **15.4: Run in Docker (skip OK without key)**

```bash
./scripts/run-tests.sh
```
Expected: E2E tests skipped, all others pass.

- [ ] **15.5: Commit**

```bash
git add tests/test_e2e.py
git commit -m "test: restore test_e2e.py from legacy

End-to-end: install plugin → load skill →
skill_view shows MCP → skill_mcp calls tool → result used."
```

---

## Step 16: Final Integration

**Files:**
- Remove: `tests/test_skill_mcp.py` (replaced by restored tests)
  OR keep as smoke test, rename to `test_smoke.py`
- Modify: `pyproject.toml` (add `mcp>=1.0,<2` version bound)
- Modify: `_metadata.py` (update version if needed)
- Verify: `Dockerfile.test` copies all new files

- [ ] **16.1: Remove or rename `test_skill_mcp.py`**

New restored tests cover all BDD scenarios. The old smoke file is
redundant. Remove it or rename to `test_smoke.py` if some tests
in it are unique.

- [ ] **16.2: Pin MCP SDK version**

```toml
# pyproject.toml line 7
"mcp>=1.0,<2",
```

- [ ] **16.3: Verify Dockerfile.test copies all files**

Check Dockerfile copies `_security.py`, `_tool_handler.py`, all
new test files.

- [ ] **16.4: Full wemake check**

```bash
.venv/bin/python -m flake8 .
```

Only project files (not `.venv/`). Expected: clean.

- [ ] **16.5: Full Docker test suite**

```bash
./scripts/run-tests.sh
```

Expected: ALL tests pass (50+ tests covering all BDD scenarios).

- [ ] **16.6: BDD coverage check**

Run test suite, verify:
- Feature 1: 3 scenarios covered
- Feature 2: 12 scenarios covered
- Feature 3: 6 scenarios covered
- Feature 4: 15 scenarios covered
- Feature 5: 9 scenarios covered
- Feature 6: 6 scenarios covered
- Feature 7: 7 scenarios covered
- Feature 8: 2 scenarios covered
- Feature 9: 3 scenarios covered
- Feature 10: 5 scenarios covered (partial — perf tests may need separate setup)
- Feature 11: schema validation in `_config.py`

- [ ] **16.7: Commit**

```bash
git add -A
git commit -m "chore: final integration — BDD coverage complete

All legacy modules restored, wemake clean, all Docker tests pass.
MCP SDK pinned to >=1.0,<2 for v2 alpha safety.
Removed redundant test_skill_mcp.py, full BDD feature coverage."
```

---

## Git Graph (expected history)

```
main: 9667f2f refactor: zero wemake errors
  │
  ├── merge/legacy-bdd
  │     │
  │     ├── feat: restore full _config.py
  │     ├── test: restore test_config.py
  │     ├── feat: restore _security.py
  │     ├── test: restore test_security.py
  │     ├── feat: expand _connection.py
  │     ├── test: restore test_connection.py
  │     ├── feat: restore _tool_handler.py
  │     ├── test: restore test_tool_handler.py
  │     ├── feat: expand _skill_view_hook.py
  │     ├── test: restore test_skill_view_hook.py
  │     ├── feat: restore plugin entrypoint
  │     ├── test: restore test_plugin_entry.py
  │     ├── test: restore test_hermes_api_contract.py
  │     ├── test: restore test_edge_cases.py
  │     ├── test: restore test_e2e.py
  │     └── chore: final integration
  │
  └── (merge to main)
```

---

## Risk Notes

1. **wemake max-complexity=6 is aggressive.** `_tool_handler.py` and
   `_connection.py` will need the most refactoring. If a function truly
   can't be split without losing clarity, document why and consider
   `# noqa: WPS231` with justification.

2. **Legacy tests use mock Hermes API.** Some tests (`test_plugin_entry`,
   `test_hermes_api_contract`) may rely on mock objects that need
   adaptation for current Docker structure.

3. **E2E test requires `HERMES_API_KEY`.** Will be skipped in CI
   without key — acceptable. Local dev must set env var for full pass.

4. **`mcp` SDK v2 alpha risk.** Pinning `<2` prevents drift but
   doesn't fix if v2 breaks v1 behavior. Monitor upstream.

5. **Test file sizes.** Several legacy tests >500 lines.
   May hit wemake `WPS202` (too many module members).
   Split if needed: `test_config.py` → `test_config_parse.py` +
   `test_config_validation.py`.

---

## Verification Checklist (pre-merge)

- [ ] `feature/merge-legacy-bdd` branch exists, based on `main`
- [ ] All 16 steps committed in order
- [ ] `flake8 .` clean on project files (not `.venv`)
- [ ] `./scripts/run-tests.sh` → all pass
- [ ] Dockerfile.test copies all source files
- [ ] `__init__.py` has correct `register(ctx)` with all imports
- [ ] `_config.py` parse_mcp_config covers all BDD F2 scenarios
- [ ] `_security.py` covers all BDD F7 scenarios
- [ ] `_connection.py` covers all BDD F3/F5 scenarios
- [ ] `_tool_handler.py` covers all BDD F4/F8 scenarios
- [ ] `_skill_view_hook.py` covers all BDD F6 scenarios
- [ ] Legacy branch `9cc7c0a` untouched (reference only)
