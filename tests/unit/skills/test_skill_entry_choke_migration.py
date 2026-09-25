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

    # 迁移清单的**逐条结论**（票据 005 要求「迁移 / 不迁移（写明风险与不修理由）」，
    # 无一条含糊）。键 = 文件相对路径，值 = (命中行数, 结论)。
    # 命中行数由命令重跑生成并在此比对：行数变了说明清单结构变了，必须重新逐条给结论，
    # 不许靠"文件在集合里"整体放行（原先的写法正是整文件放行，等于其余入口不写理由）。
    ENTRY_LEDGER = {
        "neurova/tool_executor.py": (
            1, "咽喉自身实现（`execute_skill_tool` 是唯一执行缝），保留",
        ),
        "neurova/skill_system.py": (
            3, "注册表实现本体 + 隔离执行的两条降级回退（RuntimeManager 缺席/隔离执行异常），保留",
        ),
        "neurova/tool_layers/tool_router.py": (
            1, "路由器就是咽喉内层的一档（被 `_execute_tool_core` 调用），保留",
        ),
        "neurova/skills/executor.py": (
            1, "`SkillExecutor` 协议 docstring 里的方法名（非调用点），保留",
        ),
        "neurova/router.py": (
            1, "`_agent.tool_executor` 缺席时的降级直调：真机上恒不走到（Agent 恒装配执行器），"
               "保留以保住独立注册表台架（评测/脚本）可用",
        ),
        "neurova/api/endpoints/skill.py": (
            1, "无 registry 装配的降级直调（评测台架），迁进治理面风险大于收益，登记不迁移",
        ),
    }

    def _scan(self) -> Dict[str, int]:
        hits: Dict[str, int] = {}
        for path in NEUROVA.rglob("*.py"):
            rel = path.relative_to(REPO_ROOT).as_posix()
            for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
                if ".execute_skill(" in line and "def execute_skill" not in line:
                    hits[rel] = hits.get(rel, 0) + 1
        return hits

    def test_migrated_entries_call_the_choke(self):
        """清单逐条有结论：未登记的命中点判红，登记过的必须逐条写明理由。

        清单由命令重跑生成（票面口径）：

            grep -rn '\\.execute_skill(' --include=*.py neurova/ |
                grep -v 'src-tauri|/tests/|def execute'
        """
        hits = self._scan()
        unregistered = sorted(set(hits) - set(self.ENTRY_LEDGER))
        assert unregistered == [], (
            f"出现未登记的直调入口（必须逐条给结论，不许整体放行）："
            f"{ {k: hits[k] for k in unregistered} }"
        )

    def test_ledger_reasons_are_concrete_and_counted(self):
        """每条结论必须带具体理由（不是"允许保留"这类空话）且命中数与实测一致。"""
        hits = self._scan()
        for rel, (expected, reason) in self.ENTRY_LEDGER.items():
            assert len(reason) >= 12, f"{rel} 的结论太笼统，等于没写理由：{reason!r}"
            assert hits.get(rel, 0) == expected, (
                f"{rel} 的命中数从 {expected} 变成了 {hits.get(rel, 0)}，"
                "清单结构变了：必须重新逐条给结论"
            )

    def test_ledger_is_written_down_for_humans(self):
        """台账必须同时是人类可读文档（票面要求登记，不只在测试里）。"""
        ledger = (REPO_ROOT / "docs" / "specs" / "2026-09-21-tool-experience-loop"
                  / "入口迁移台账.md")
        assert ledger.exists(), "迁移台账没人可读的落点"
        text = ledger.read_text(encoding="utf-8")
        for rel in self.ENTRY_LEDGER:
            assert rel in text, f"台账缺少 {rel} 的逐条结论"
        assert "不迁移" in text and "风险" in text

    def test_ledger_has_no_stale_entries(self):
        """登记项必须仍然存在：删掉的入口不能留在台账里充数。"""
        hits = self._scan()
        stale = sorted(set(self.ENTRY_LEDGER) - set(hits))
        assert stale == [], f"台账里的入口在代码里已不存在：{stale}"


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
