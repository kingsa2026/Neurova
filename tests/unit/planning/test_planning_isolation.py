"""PlanStore 三层隔离测试（TDD 红绿）—— docs/isolation-fit-assessment.md §3.3

三层 = (agent_id, neuser_id, user_id)；工具链路的身份来源是 tool_executor 的
_agent_identity() → (user_id, agent_id)（JWT sub，neuser_id 与 user_id 同源）。

修复目标：
- plans 表带 (agent_id, user_id) 归属；plan_id 在归属内唯一（双用户同名计划共存）
- list/get/mark_step/delete/update 全部按归属过滤（跨用户不可见）
- set_active/get_active 的活跃指针按归属隔离（互不干扰）
- 旧 schema（无归属列）自动迁移：存量行补 ("default","default") 归属
- tool_executor 分发时注入调用者身份
"""

import json
import sqlite3

import pytest


def _tool(tmp_path, agent_id="default", user_id="default"):
    from neurova.planning import PlanningTool

    return PlanningTool(db_path=str(tmp_path / "plans.db")), (agent_id, user_id)


async def _run(tool, owner, **kwargs):
    return await tool.run_command(
        owner_agent_id=owner[0], owner_user_id=owner[1], **kwargs
    )


class TestOwnerIsolation:
    @pytest.mark.asyncio
    async def test_same_plan_id_different_users_coexist(self, tmp_path):
        tool, (a_agent, a_user) = _tool(tmp_path)
        _, (b_agent, b_user) = _tool(tmp_path)
        owner_a = (a_agent, a_user)
        owner_b = (b_agent, "user-b")

        await _run(tool, owner_a, command="create", plan_id="p1", title="A 的计划", steps=["a1"])
        await _run(tool, owner_b, command="create", plan_id="p1", title="B 的计划", steps=["b1"])

        got_a = await _run(tool, owner_a, command="get", plan_id="p1")
        got_b = await _run(tool, owner_b, command="get", plan_id="p1")
        assert "A 的计划" in got_a["data"]["text"]
        assert "B 的计划" in got_b["data"]["text"]
        assert "A 的计划" not in got_b["data"]["text"]
        assert "B 的计划" not in got_a["data"]["text"]

    @pytest.mark.asyncio
    async def test_list_scoped_by_owner(self, tmp_path):
        tool, (a_agent, a_user) = _tool(tmp_path)
        owner_a = (a_agent, a_user)
        owner_b = (a_agent, "user-b")

        await _run(tool, owner_a, command="create", plan_id="pa", title="A-only", steps=["a"])
        await _run(tool, owner_b, command="create", plan_id="pb", title="B-only", steps=["b"])

        list_a = await _run(tool, owner_a, command="list")
        ids_a = [p["plan_id"] for p in list_a["data"]]
        assert "pa" in ids_a and "pb" not in ids_a

        list_b = await _run(tool, owner_b, command="list")
        ids_b = [p["plan_id"] for p in list_b["data"]]
        assert "pb" in ids_b and "pa" not in ids_b

    @pytest.mark.asyncio
    async def test_active_pointer_isolated_per_owner(self, tmp_path):
        tool, (a_agent, a_user) = _tool(tmp_path)
        owner_a = (a_agent, a_user)
        owner_b = (a_agent, "user-b")

        await _run(tool, owner_a, command="create", plan_id="pa", title="A", steps=["a"])
        await _run(tool, owner_b, command="create", plan_id="pb", title="B", steps=["b"])

        await _run(tool, owner_a, command="set_active", plan_id="pa")
        await _run(tool, owner_b, command="set_active", plan_id="pb")

        active_a = await _run(tool, owner_a, command="get")  # 缺省取本归属活跃计划
        active_b = await _run(tool, owner_b, command="get")
        assert active_a["data"]["plan_id"] == "pa"
        assert active_b["data"]["plan_id"] == "pb"

    @pytest.mark.asyncio
    async def test_mark_and_delete_scoped(self, tmp_path):
        tool, (a_agent, a_user) = _tool(tmp_path)
        owner_a = (a_agent, a_user)
        owner_b = (a_agent, "user-b")

        await _run(tool, owner_a, command="create", plan_id="p1", title="A", steps=["a"])
        await _run(tool, owner_b, command="create", plan_id="p1", title="B", steps=["b"])

        # A 标记/删除只影响 A 自己的
        await _run(tool, owner_a, command="mark_step", plan_id="p1", step_index=0, step_status="completed")
        got_b = await _run(tool, owner_b, command="get", plan_id="p1")
        assert "[ ] b" in got_b["data"]["text"]  # B 的不受影响

        await _run(tool, owner_a, command="delete", plan_id="p1")
        still_b = await _run(tool, owner_b, command="get", plan_id="p1")
        assert still_b["success"] is True  # B 的同名计划仍在
        gone_a = await _run(tool, owner_a, command="get", plan_id="p1")
        assert gone_a["success"] is False


class TestLegacyMigration:
    @pytest.mark.asyncio
    async def test_legacy_table_migrated_with_default_owner(self, tmp_path):
        """旧 schema（plan_id 单列主键、无归属列）打开时自动迁移并补 default 归属"""
        import sqlite3

        from neurova.planning import PlanningTool

        db = str(tmp_path / "plans.db")
        # 手工造旧表
        conn = sqlite3.connect(db)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS plans (plan_id TEXT PRIMARY KEY, title TEXT NOT NULL, "
            "steps TEXT NOT NULL, step_statuses TEXT NOT NULL, step_notes TEXT NOT NULL, "
            "is_active INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO plans VALUES ('legacy1', '旧计划', '[\"s1\"]', '[\"not_started\"]', '[\"\"]', 1, 't', 't')"
        )
        conn.commit()
        conn.close()

        tool = PlanningTool(db_path=db)
        got = await tool.run_command(command="get", plan_id="legacy1")  # default 归属可见
        assert got["success"] is True
        assert "旧计划" in got["data"]["text"]
        assert "[ ] s1" in got["data"]["text"]

    def test_new_rows_carry_owner_columns(self, tmp_path):
        """新表结构带归属列，写入行记录创建者"""
        import sqlite3

        from neurova.planning import PlanningTool

        db = str(tmp_path / "plans.db")
        tool = PlanningTool(db_path=db)

        import asyncio

        asyncio.run(
            tool.run_command(
                owner_agent_id="default", owner_user_id="user-7",
                command="create", plan_id="p1", title="T", steps=["a"],
            )
        )
        conn = sqlite3.connect(db)
        row = conn.execute(
            "SELECT agent_id, user_id FROM plans WHERE plan_id = 'p1'"
        ).fetchone()
        conn.close()
        assert row == ("default", "user-7")


class TestExecutorIdentity:
    @pytest.mark.asyncio
    async def test_executor_passes_caller_identity(self, tmp_path):
        """tool_executor 分发时把调用者身份注入归属"""
        from unittest.mock import MagicMock, patch

        from neurova.planning import PlanStore
        from neurova.tool_executor import ToolExecutor

        exe = ToolExecutor(_AgentStub())
        store = PlanStore(str(tmp_path / "plans.db"))

        with (
            patch("neurova.planning.get_planning_store", return_value=store),
            patch.object(type(exe), "_agent_identity", MagicMock(return_value=("user-42", "default"))),
        ):
            created = await exe._execute_builtin_tool(
                "planning",
                {"command": "create", "plan_id": "mine", "title": "T", "steps": ["a"]},
            )
        assert created["success"] is True

        row = store.get("mine", agent_id="default", user_id="user-42")
        assert row is not None
        # 其他用户不可见
        assert store.get("mine", agent_id="default", user_id="someone-else") is None


class _AgentStub:
    pass
