# Bug Fix: Agent 无法调用工具 (Agent Tool Calling Failure)

**Date:** 2026-06-21
**Severity:** Critical (agent tool calling completely broken)
**Status:** Fixed

## Summary

When an agent attempts to invoke tools (e.g., `memory_search`, `web_search`, `file_operation`), the tool execution pipeline fails silently. The `ToolRouter` cannot route tool calls because `SkillRegistry` is `None` at initialization time.

## Root Cause

**File:** `neurova/agent_core.py`

### Initialization Order Bug

The `Agent` class has a multi-phase initialization process. The critical path is:

1. `__init__()` → calls `init_management()` → sets `self._skill_registry = None` (line 403)
2. Later, the system calls `init_tools()` → tries to create `ToolRouter` → calls `a.tool_router.set_skill_manager(a.skill_registry)`
3. `a.skill_registry` is a property that returns `self._skill_registry`, which is still `None`

The `SkillRegistry` is supposed to be lazily initialized in `_init_router()` (line 1041-1043), but `_init_router()` is not called during the standard initialization path — it's only called later when certain routing features are needed. By the time `ToolRouter` is constructed, `_skill_registry` is still `None`.

### Data Flow (Broken)

```
Agent.__init__()
  → init_management()
    → self._skill_registry = None          # line 403
  → init_tools()
    → ToolRouter()                         # line 582
    → tool_router.set_skill_manager(None)  # skill_registry is None ❌
    → ToolRouter can't route any tools
```

### Why _init_router() wasn't called

`_init_router()` is only called from:
- `inject_context()` — only runs during active chat conversations
- `_internal_execute()` — also chat-path only

Neither is called during agent bootstrap/initialization.

## Fix

**File:** `neurova/agent_core.py` (lines 570-578)

Added lazy SkillRegistry initialization in `init_tools()` **before** ToolRouter creation:

```python
# [BUGFIX] 提前初始化 SkillRegistry，避免 ToolRouter 获得 None
if a._skill_registry is None:
    try:
        from neurova.skill_system import create_default_skills
        a._skill_registry = create_default_skills(memory_manager=a.memory_manager)
        logger.info("Agent %s: SkillRegistry 在 init_tools 中提前初始化", a.config.name)
    except Exception as _e:
        logger.warning("init_tools 中提前初始化 SkillRegistry 失败: %s", _e)
        a._skill_registry = None
```

This ensures that when `ToolRouter` is constructed and calls `set_skill_manager(a.skill_registry)`, it receives a valid `SkillRegistry` instance.

### Supporting Fix: Lazy Import in `skill_system/__init__.py`

**File:** `neurova/skill_system/__init__.py` (lines 77-85)

Added `create_default_skills` to the `__getattr__` lazy-import handler to prevent circular import issues:

```python
elif name == "create_default_skills":
    from neurova.skill_system import create_default_skills as _cds
    return _cds
```

### Data Flow (Fixed)

```
Agent.__init__()
  → init_management()
    → self._skill_registry = None
  → init_tools()
    → _skill_registry is None → create_default_skills()
    → SkillRegistry initialized ✓
    → ToolRouter()
    → tool_router.set_skill_manager(skill_registry)  # Valid! ✓
    → ToolRouter can route tools properly ✓
```

## Verification

To verify the fix:

1. Start the backend: `python start.py --backend`
2. Observe logs for:
   - `"Agent X: SkillRegistry 在 init_tools 中提前初始化"` (success)
   - Or `"init_tools 中提前初始化 SkillRegistry 失败"` (failure — check dependencies)
3. Create an agent and send a message requesting a tool call (e.g., "search for recent news")
4. Verify the agent correctly invokes the tool and returns results

## Files Changed

- `neurova/agent_core.py` — Added lazy SkillRegistry initialization in `init_tools()` before ToolRouter creation
- `neurova/skill_system/__init__.py` — Added `create_default_skills` to `__getattr__` lazy-import handler

## Technical Details

### Tool Calling Pipeline

```
LLM Response
  → agent loop (openai_loop.py / anthropic_loop.py)
    → handle_tool_calls()
      → tool_executor.execute_tool()
        → ToolRouter.resolve_tool()
          → SkillRegistry.get_skill() / execute_skill()
```

### Key Classes

| Class | File | Role |
|-------|------|------|
| `ToolRouter` | `neurova/tool_layers/` | Routes tool names to handlers (built-in vs skill) |
| `SkillRegistry` | `neurova/skill_system/` | Manages skill tools, executes skills by name |
| `BuiltinToolRegistry` | `neurova/agent_core.py` | Registers built-in tools (computer_use, etc.) |
| `create_default_skills()` | `neurova/skill_system/` | Factory to create MemorySkill, WebSearchSkill, etc. |

## Prevention

1. Add test for initialization order: verify `skill_registry` is not `None` after `init_tools()`
2. Consider using an explicit initialization state machine rather than relying on lazy initialization order
3. Add invariant checks in `set_skill_manager()` to catch `None` values early
