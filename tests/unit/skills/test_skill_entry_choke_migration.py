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
