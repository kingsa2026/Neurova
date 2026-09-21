"""005 · 把剩下所有绕过咽喉的执行入口迁干净（扩展—迁移—收缩）。

咽喉 = `ToolExecutor.execute_skill_tool`：一次执行同时拿到票据、`on_tool_executed`
（肌肉记忆/生命周期）、统一治理预检、hooks 与 per-tool 超时。本文件钉三件事：

1. **单工具执行入口单源**：各入口改指咽喉暴露的稳定入口，不再直接调
   `SkillRegistry.execute_skill`；
2. **`file_operation._base_dir` 沙箱根注入单源**：`router.py` 与
   `agent/loops/base.py` 曾是同一份注入的两处同形实现，现收口为一处 helper，
   守卫锁住"不得出现第三处"；
3. **上下文可见性**：`scheduler` 那条同步壳里起 `asyncio.run`，轮级上下文
   （轮首 `begin_task` 建的票据上下文）必须在新事件循环里可见，否则静默零票。
"""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from typing import Any, Dict, List

import pytest

from neurova.skills.sandbox_root import inject_sandbox_root

REPO_ROOT = Path(__file__).resolve().parents[3]
NEUROVA = REPO_ROOT / "neurova"


class TestSandboxRootSingleSource:
    def test_injection_uses_agent_workspace(self):
        agent = type("A", (), {"workspace_path": "/tmp/ws"})()
        assert inject_sandbox_root(agent, "file_operation", {})["_base_dir"] == "/tmp/ws"

    def test_non_file_operation_untouched(self):
        agent = type("A", (), {"workspace_path": "/tmp/ws"})()
        assert "_base_dir" not in inject_sandbox_root(agent, "memory_search", {})

    def test_missing_workspace_falls_back_to_dot(self):
        agent = type("A", (), {})()
        assert inject_sandbox_root(agent, "file_operation", {})["_base_dir"] == "."

    def test_no_second_implementation_in_repo(self):
        """守卫：`_base_dir` 的注入只允许出现在单源 helper 与咽喉内。"""
        allowed = {
            "neurova/skills/sandbox_root.py",
            "neurova/tool_executor.py",
        }
        offenders: List[str] = []
        for path in NEUROVA.rglob("*.py"):
            rel = path.relative_to(REPO_ROOT).as_posix()
            if rel in allowed:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if '"_base_dir":' not in text:
                continue
            # 消费方读 `_base_dir` 不算注入（技能执行体 / 注释）
            offenders.append(rel)
        assert offenders == [], (
            "沙箱根注入出现第二处实现（必须收口到 skills/sandbox_root.py）：" f"{offenders}"
        )

    def test_migrated_entries_call_the_choke(self):
        """迁移清单逐条核对：入口改指咽喉，不再直调 `registry.execute_skill`。

        清单由命令重跑生成（票面口径），本用例把它钉成可复算的守卫：
        ```
        grep -rn "\\.execute_skill(" --include=*.py neurova/ | grep -v "src-tauri\\|/tests/\\|def execute"
        ```
        """
        # 允许保留的位置（各有明确理由，逐条登记）：
        # - `tool_executor.py`：咽喉自身的实现；
        # - `skill_system.py`：注册表实现（`SkillRegistry.execute_skill`）；
        # - `tool_layers/tool_router.py`：它**就是**咽喉内层的一档，被咽喉调用；
        # - `skills/executor.py`：`SkillExecutor` 协议注释，不是调用点；
        # - `router.py` / `api/endpoints/skill.py`：无 Agent/执行器时的降级分支
        #   （评测、脚本、独立注册表场景——真机上这两条分支恒不走到）。
        allowed = {
            "neurova/tool_executor.py",
            "neurova/skill_system.py",
            "neurova/tool_layers/tool_router.py",
            "neurova/skills/executor.py",
            "neurova/router.py",
            "neurova/api/endpoints/skill.py",
        }
        # 登记"不迁移"的入口：`api/endpoints/skill.py:425` 的降级直调——它只在
        # 真 agent 或其执行器缺席时可达（评测/脚本路径），迁移它会把评测台架
        # 也拖进治理面，风险大于收益。
        offenders: List[str] = []
        for path in NEUROVA.rglob("*.py"):
            rel = path.relative_to(REPO_ROOT).as_posix()
            if rel in allowed:
                continue
            for lineno, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                if ".execute_skill(" in line and "def execute_skill" not in line:
                    offenders.append(f"{rel}:{lineno}")
        assert offenders == [], f"仍有入口直调 registry.execute_skill（应改走咽喉）：{offenders}"


class TestSchedulerContextVisibility:
    """同步壳里起 `asyncio.run`：轮级上下文必须跨事件循环可见。"""

    def test_turn_context_is_visible_inside_new_event_loop(self):
        from neurova.core import turn_context as tc

        tc.reset_turn_tool_messages()
        tc.set_turn_skill_view(__import__("neurova.skills.skill_visibility", fromlist=["SkillView"]).SkillView("a1"))

        async def _inner():
            return tc.get_turn_skill_view()

        view = asyncio.run(_inner())
        assert view is not None and view.agent_id == "a1", (
            "新事件循环里读不到轮级上下文——scheduler 那条入口会静默零票"
        )
        tc.clear_turn_state()


class TestToolEngineReadEntries:
    """005 残留：把 `ToolEngine` 当**入口**用的两处读取面，行为是"静默零"。

    `collaboration/neurflow/{adapters,node_registry}.py` 都写
    `from neurova.execution_engine.tool_engine import get_tool_engine` —— 该模块
    **没有**这个函数，所以 `adapters._get_tool_engine()` 恒 None（`sync_tools`
    恒 0），`node_registry._sync_tools_from_engine` 恒 `return 0`。工具节点目录
    因此永远空着，而调用方读到的 0 与"这台机器真的没有工具"分不开。

    即使导入修好，两处还按 dict 取字段（`tool['name']` / `tool_def.get("name")`），
    而 `ToolEngine.list_tools()` 返回的是 `ToolDefinition` 数据类 —— 仍会炸。
    """

    def test_engine_lookup_shares_one_source_with_mcp_registration(self):
        """引擎读取必须取到 MCP 注册所落的那个单例（同一个事实源）。"""
        from neurova.api.endpoints import tool_layers as api
        from neurova.collaboration.neurflow import adapters

        assert adapters._get_tool_engine() is api.get_tool_engine(), (
            "_get_tool_engine() 取到的不是进程里的工具引擎单例"
            "（导入的 get_tool_engine 在该模块根本不存在，恒 None）"
        )

    def test_sync_tools_syncs_real_tool_definitions(self):
        """真实 `ToolDefinition` 列表必须能同步成节点（不是只认 dict）。"""
        from unittest.mock import MagicMock

        from neurova.api.endpoints import tool_layers as api
        from neurova.collaboration.neurflow import adapters

        engine = api.get_tool_engine()
        added = not engine.get_tool("__sync_probe__")
        if added:
            engine.register_tool("__sync_probe__", lambda: None, description="探针")
        try:
            registry = MagicMock()
            assert adapters.sync_tools(registry) >= 1, "工具节点同步恒 0（引擎取不到）"
            node = registry.register.call_args[0][0]
            assert node.type.startswith("tool:__sync_probe__") or node.source == "tool"
            assert node.label == "__sync_probe__", f"节点名取错：{node.label!r}"
        finally:
            if added:
                engine.unregister_tool("__sync_probe__")

    def test_node_registry_sync_reads_real_tool_definitions(self):
        """`node_registry._sync_tools_from_engine` 同样必须认数据类定义。"""
        from unittest.mock import MagicMock

        from neurova.api.endpoints import tool_layers as api
        from neurova.collaboration.neurflow import node_registry as nr

        engine = api.get_tool_engine()
        added = not engine.get_tool("__sync_probe__")
        if added:
            engine.register_tool("__sync_probe__", lambda: None, description="探针")
        try:
            registry = MagicMock()
            count = nr._sync_tools_from_engine(registry)
            assert count >= 1, "同步恒 0（导入的 get_tool_engine 不存在 → 静默 return 0）"
        finally:
            if added:
                engine.unregister_tool("__sync_probe__")


class TestToolExecuteEndpointGoesThroughChoke:
    """005 残留：`/tool-layers/tools/execute` 不能再把 `ToolEngine` 当入口。

    `ToolEngine` 是咽喉**内层**（`tool_executor._execute_tool_core` 调它）。
    端点直接调它，就绕过了票据、`on_tool_executed`、治理预检与 hooks ——
    与 003 收编前的原生链同型。有 agent/执行器时必须走咽喉；引擎只在
    "无 agent 的评测/脚本" 那条降级分支里用。
    """

    @pytest.mark.asyncio
    async def test_agent_executor_is_preferred_over_raw_engine(self):
        from unittest.mock import AsyncMock, MagicMock, patch

        from neurova.api.endpoints import tool_layers
        from neurova.api.endpoints.tool_layers import ToolExecuteRequest, execute_tool

        engine = MagicMock()
        engine.execute_with_safeguards = AsyncMock(return_value={"raw": "bypass"})

        executor = MagicMock()
        executor.execute = AsyncMock(return_value={"ok": "through-choke"})
        executor._result_is_success = lambda payload: bool(payload.get("ok"))
        agent = MagicMock()
        agent.tool_executor = executor

        with patch.object(tool_layers, "get_tool_engine", return_value=engine), \
             patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            response = await execute_tool(
                ToolExecuteRequest(tool_name="calculator", arguments={"expr": "1+1"}, timeout=5)
            )

        assert executor.execute.await_count == 1, "端点没走咽喉（agent.tool_executor）"
        assert engine.execute_with_safeguards.await_count == 0, (
            "端点仍把 ToolEngine 当入口用（绕过票据/钩子/治理）"
        )
        assert response["code"] == 0

    @pytest.mark.asyncio
    async def test_engine_still_used_when_no_agent(self):
        """反向锁：无 agent 的评测/脚本路径仍可用引擎（不是一刀切禁掉）。"""
        from unittest.mock import AsyncMock, MagicMock, patch

        from neurova.api.endpoints import tool_layers
        from neurova.api.endpoints.tool_layers import ToolExecuteRequest, execute_tool

        engine = MagicMock()
        engine.execute_with_safeguards = AsyncMock(return_value={"ok": True})

        with patch.object(tool_layers, "get_tool_engine", return_value=engine), \
             patch("neurova.api.endpoints.get_agent_instance", return_value=None):
            response = await execute_tool(
                ToolExecuteRequest(tool_name="calculator", arguments={}, timeout=5)
            )

        assert engine.execute_with_safeguards.await_count == 1
        assert response["code"] == 0


class TestToolEngineEntryGuard:
    """守卫：`ToolEngine` 的取用只有一个源，且不得被当成执行入口。

    `grep -rn "from neurova.execution_engine.tool_engine import" neurova/` 的
    结果必须只剩"取类/取枚举"这条合法用法——取 `get_tool_engine` 会 ImportError
    （该模块没有这个函数），再被吞成静默 0/None。
    """

    def test_no_phantom_get_tool_engine_import(self):
        offenders: List[str] = []
        for path in NEUROVA.rglob("*.py"):
            rel = path.relative_to(REPO_ROOT).as_posix()
            for lineno, line in enumerate(
                path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1
            ):
                if "execution_engine.tool_engine import" in line and "get_tool_engine" in line:
                    offenders.append(f"{rel}:{lineno}")
        assert offenders == [], (
            "`neurova.execution_engine.tool_engine` 没有 get_tool_engine，"
            f"这行会 ImportError 并被吞成静默零（改用 api.endpoints.tool_layers）：{offenders}"
        )
