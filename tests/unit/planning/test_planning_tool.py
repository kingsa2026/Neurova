"""PlanningTool 计划即工具（TDD 红绿）—— 对比文档 P5

对标 OpenManus PlanningTool 的 7 命令语义（create/update/list/get/set_active/
mark_step/delete），关键差异：计划持久化到 SQLite（OpenManus 是进程内 dict，
重启即失——Neurova 用自身强项反超），跨会话/重启后计划与活跃指针自动还原。

命名说明：工具入口方法是 run_command（而非 execute），与 sqlite3.Connection.execute
做显式区分。
"""

import pytest


@pytest.fixture
def tool(tmp_path):
    from neurova.planning import PlanningTool

    return PlanningTool(db_path=str(tmp_path / "plans.db"))


def _data(result):
    return result.get("data")


class TestCreateAndGet:
    @pytest.mark.asyncio
    async def test_create_plan_defaults_not_started(self, tool):
        result = await tool.run_command(command="create", plan_id="p1", title="发布准备", steps=["写文档", "跑测试", "部署"])
        assert result["success"] is True
        plan = await tool.run_command(command="get", plan_id="p1")
        text = _data(plan)["text"]
        assert "发布准备" in text
        assert "[ ] 写文档" in text and "[ ] 跑测试" in text
        assert "0/3" in text  # 进度统计

    @pytest.mark.asyncio
    async def test_create_duplicate_plan_id_rejected(self, tool):
        await tool.run_command(command="create", plan_id="p1", title="T", steps=["a"])
        result = await tool.run_command(command="create", plan_id="p1", title="T2", steps=["b"])
        assert result["success"] is False
        assert "已存在" in result["error"]

    @pytest.mark.asyncio
    async def test_create_requires_title_and_steps(self, tool):
        result = await tool.run_command(command="create", plan_id="p1", title="", steps=[])
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_get_renders_status_marks_and_notes(self, tool):
        await tool.run_command(command="create", plan_id="p1", title="T", steps=["a", "b"])
        await tool.run_command(command="mark_step", plan_id="p1", step_index=0, step_status="completed")
        await tool.run_command(command="mark_step", plan_id="p1", step_index=1, step_status="in_progress", step_notes="进行中")
        plan = await tool.run_command(command="get", plan_id="p1")
        text = _data(plan)["text"]
        assert "[✓] a" in text
        assert "[→] b" in text and "进行中" in text
        assert "1/2" in text


class TestUpdateAndMark:
    @pytest.mark.asyncio
    async def test_update_steps_preserves_existing_status(self, tool):
        await tool.run_command(command="create", plan_id="p1", title="T", steps=["a", "b"])
        await tool.run_command(command="mark_step", plan_id="p1", step_index=0, step_status="completed")
        await tool.run_command(command="update", plan_id="p1", steps=["a", "b", "c"])
        plan = await tool.run_command(command="get", plan_id="p1")
        text = _data(plan)["text"]
        assert "[✓] a" in text  # 原有状态保留
        assert "[ ] c" in text  # 新增步默认 not_started
        assert "1/3" in text

    @pytest.mark.asyncio
    async def test_mark_step_validates_index_and_status(self, tool):
        await tool.run_command(command="create", plan_id="p1", title="T", steps=["a"])
        bad_index = await tool.run_command(command="mark_step", plan_id="p1", step_index=5, step_status="completed")
        bad_status = await tool.run_command(command="mark_step", plan_id="p1", step_index=0, step_status="flying")
        assert bad_index["success"] is False
        assert bad_status["success"] is False

    @pytest.mark.asyncio
    async def test_unknown_command_rejected(self, tool):
        result = await tool.run_command(command="hack", plan_id="p1")
        assert result["success"] is False


class TestListActiveDelete:
    @pytest.mark.asyncio
    async def test_list_reports_active_flag_and_progress(self, tool):
        await tool.run_command(command="create", plan_id="p1", title="T1", steps=["a", "b"])
        await tool.run_command(command="create", plan_id="p2", title="T2", steps=["x"])
        await tool.run_command(command="set_active", plan_id="p2")
        listing = await tool.run_command(command="list")
        plans = {item["plan_id"]: item for item in _data(listing)}
        assert plans["p1"]["is_active"] is False
        assert plans["p2"]["is_active"] is True
        assert plans["p1"]["total_steps"] == 2

    @pytest.mark.asyncio
    async def test_set_active_and_get_without_plan_id(self, tool):
        await tool.run_command(command="create", plan_id="p1", title="T1", steps=["a"])
        await tool.run_command(command="create", plan_id="p2", title="T2", steps=["x"])
        await tool.run_command(command="set_active", plan_id="p2")
        active = await tool.run_command(command="get")  # 缺省取活跃计划
        assert _data(active)["plan_id"] == "p2"

    @pytest.mark.asyncio
    async def test_delete_clears_active_pointer(self, tool):
        await tool.run_command(command="create", plan_id="p1", title="T1", steps=["a"])
        await tool.run_command(command="create", plan_id="p2", title="T2", steps=["x"])
        await tool.run_command(command="set_active", plan_id="p1")
        await tool.run_command(command="delete", plan_id="p1")
        result = await tool.run_command(command="get")  # 活跃指针已清除
        assert result["success"] is False


class TestPersistence:
    """SQLite 持久化：重建实例后计划与活跃指针完整还原（反超 OpenManus 进程内 dict）"""

    @pytest.mark.asyncio
    async def test_plans_survive_store_rebuild(self, tool, tmp_path):
        await tool.run_command(command="create", plan_id="p1", title="持久化", steps=["a", "b"])
        await tool.run_command(command="mark_step", plan_id="p1", step_index=0, step_status="completed", step_notes="done")
        await tool.run_command(command="set_active", plan_id="p1")

        from neurova.planning import PlanningTool

        reborn = PlanningTool(db_path=str(tmp_path / "plans.db"))
        plan = await reborn.run_command(command="get")  # 活跃指针也还原
        assert _data(plan)["plan_id"] == "p1"
        text = _data(plan)["text"]
        assert "[✓] a" in text and "done" in text
        assert "持久化" in text

    @pytest.mark.asyncio
    async def test_store_write_goes_to_sqlite_file(self, tool, tmp_path):
        await tool.run_command(command="create", plan_id="p1", title="T", steps=["a"])
        import os

        assert os.path.exists(str(tmp_path / "plans.db"))


class TestAgentIntegration:
    """接入 builtin_tools schema + tool_executor 分发"""

    def test_schema_registered(self):
        from neurova.builtin_tools import _BUILTIN_SCHEMAS

        assert "planning" in _BUILTIN_SCHEMAS
        params = _BUILTIN_SCHEMAS["planning"]["parameters"]
        commands = params["properties"]["command"]["enum"]
        assert set(commands) == {"create", "update", "list", "get", "set_active", "mark_step", "delete"}

    @pytest.mark.asyncio
    async def test_executor_dispatches_to_store(self, tmp_path):
        from unittest.mock import patch

        from neurova.planning import PlanStore
        from neurova.tool_executor import ToolExecutor

        exe = ToolExecutor(_AgentStub())
        real_store = PlanStore(str(tmp_path / "plans.db"))
        with patch("neurova.planning.get_planning_store", return_value=real_store):
            created = await exe._execute_builtin_tool(
                "planning", {"command": "create", "plan_id": "px", "title": "T", "steps": ["a"]}
            )
            assert created["success"] is True
            got = await exe._execute_builtin_tool("planning", {"command": "get", "plan_id": "px"})
        assert "[ ] a" in got["data"]["text"]


class _AgentStub:
    """tool_executor 仅在广播事件时访问 agent 属性；单测用最小桩"""
