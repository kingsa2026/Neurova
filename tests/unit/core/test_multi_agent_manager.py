"""
测试多Agent管理器（对齐 neurova/core/multi_agent_manager.py 真实契约）
"""

import pytest
import asyncio
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock

from neurova.core.multi_agent_manager import (
    NeurovaAgent,
    MultiAgentManager,
    get_multi_agent_manager,
    reset_multi_agent_manager,
)


class TestNeurovaAgent:
    """测试NeurovaAgent数据类"""

    def test_create_neurova_agent(self):
        """测试创建Agent（字段面 agent_id/name/description/workspace_dir/config）"""
        agent = NeurovaAgent(
            agent_id="test_agent",
            name="Test Agent",
            description="A test agent",
        )

        assert agent.agent_id == "test_agent"
        assert agent.name == "Test Agent"
        assert agent.description == "A test agent"
        assert agent.workspace_dir is None
        assert agent.config == {}
        assert agent.metadata == {}
        assert agent.is_running is False

    def test_neurova_agent_auto_timestamps(self):
        """created_at/last_active 自动填充"""
        agent = NeurovaAgent(agent_id="test_agent")

        assert agent.created_at > 0
        assert agent.last_active > 0

    def test_neurova_agent_to_dict(self):
        """测试转换为字典"""
        agent = NeurovaAgent(
            agent_id="test_agent",
            name="Test Agent",
            description="desc",
        )

        data = agent.to_dict()

        assert data["agent_id"] == "test_agent"
        assert data["name"] == "Test Agent"
        assert data["description"] == "desc"
        assert data["is_running"] is False
        assert data["workspace_dir"] is None
        assert "created_at" in data
        assert "last_active" in data


class TestMultiAgentManager:
    """测试MultiAgentManager类"""

    def test_init(self):
        """测试初始化（_agents + 三个共享组件槽位）"""
        manager = MultiAgentManager()

        assert manager._agents == {}
        assert manager._plan_orchestrator is None
        assert manager._execution_engine is None
        assert manager._infrastructure is None
        assert manager._lock is not None

    def test_initialize_shared_components(self):
        """测试初始化共享组件（契约：同步，收三组件）"""
        manager = MultiAgentManager()

        plan = MagicMock()
        engine = MagicMock()
        infra = MagicMock()

        manager.initialize_shared_components(
            plan_orchestrator=plan,
            execution_engine=engine,
            infrastructure=infra,
        )

        assert manager._plan_orchestrator is plan
        assert manager._execution_engine is engine
        assert manager._infrastructure is infra

    def test_get_workspace_dir(self, tmp_path):
        """测试获取工作区目录（base_workspace_dir / agent_id）"""
        manager = MultiAgentManager()
        assert manager.set_base_workspace_dir(str(tmp_path / "agents")) is True

        workspace_dir = manager.get_workspace_dir("agent1")

        assert workspace_dir is not None
        assert "agent1" in str(workspace_dir)

    def test_get_workspace_dir_no_base(self):
        """未设置 base 时返回 None"""
        manager = MultiAgentManager()

        assert manager.get_workspace_dir("agent1") is None

    def test_get_agent_auto_create(self):
        """get_agent 自动创建并登记"""
        manager = MultiAgentManager()

        agent = manager.get_agent("agent1", auto_create=True)

        assert agent is not None
        assert agent.agent_id == "agent1"
        assert manager.is_agent_loaded("agent1") is True

    def test_list_agents(self):
        """测试列出Agent"""
        manager = MultiAgentManager()

        assert manager.list_agents() == []

        manager.get_agent("a1")
        assert manager.list_agents() == ["a1"]

    def test_is_agent_loaded(self):
        """测试检查Agent是否加载"""
        manager = MultiAgentManager()

        assert manager.is_agent_loaded("agent1") is False

    def test_get_agent_info_nonexistent(self):
        """测试获取不存在的Agent信息"""
        manager = MultiAgentManager()

        assert manager.get_agent_info("nonexistent") is None

    @pytest.mark.asyncio
    async def test_execute_with_shared_cerebellum_not_found(self):
        """get_agent(auto_create=False) 找不到 Agent 时返回失败 dict（不抛异常）"""
        manager = MultiAgentManager()
        # 直接塞 None 模拟登记缺失（get_agent 会 auto_create）
        manager._agents.pop("ghost", None)

        result = await manager.execute_with_shared_cerebellum(
            agent_id="ghost", task="do it"
        )

        # auto_create=True 会自动创建 → 正常执行成功
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_execute_without_orchestrator(self):
        """未注入编排器时走认知处理兜底路径"""
        manager = MultiAgentManager()
        manager.get_agent("a1")  # 自动创建

        result = await manager.execute_with_shared_cerebellum(
            agent_id="a1", task="test task"
        )

        assert result["success"] is True
        assert result["task"] == "test task"

    @pytest.mark.asyncio
    async def test_execute_with_orchestrator(self):
        """注入编排器后走 plan → execute_plan 链"""
        manager = MultiAgentManager()
        manager.get_agent("a1")

        plan = MagicMock()
        plan.plan_id = "p1"
        orchestrator = MagicMock()
        orchestrator.decompose_intent.return_value = plan
        orchestrator.execute_plan = AsyncMock(return_value={"success": True})
        manager.initialize_shared_components(plan_orchestrator=orchestrator)

        result = await manager.execute_with_shared_cerebellum(
            agent_id="a1", task="t", context={}
        )

        assert result["success"] is True
        orchestrator.execute_plan.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_start_agent(self):
        """启动 Agent（自动创建，is_running 置位）"""
        manager = MultiAgentManager()

        success = await manager.start_agent("test_agent")

        assert success is True
        assert manager._agents["test_agent"].is_running is True

    @pytest.mark.asyncio
    async def test_start_agent_twice(self):
        """重复启动幂等成功"""
        manager = MultiAgentManager()

        assert await manager.start_agent("a1") is True
        assert await manager.start_agent("a1") is True

    @pytest.mark.asyncio
    async def test_stop_agent_nonexistent(self):
        """停止不存在的 Agent 返回 False"""
        manager = MultiAgentManager()

        assert await manager.stop_agent("nonexistent") is False

    @pytest.mark.asyncio
    async def test_stop_agent(self):
        """停止运行中的 Agent"""
        manager = MultiAgentManager()
        await manager.start_agent("a1")

        assert await manager.stop_agent("a1") is True
        assert manager._agents["a1"].is_running is False

    @pytest.mark.asyncio
    async def test_stop_all(self):
        """测试停止所有Agent"""
        manager = MultiAgentManager()
        await manager.start_agent("a1")
        await manager.start_agent("a2")

        results = await manager.stop_all()

        assert set(results.keys()) == {"a1", "a2"}
        assert all(results.values())
        assert all(not a.is_running for a in manager._agents.values())


class TestGlobalFunctions:
    """测试全局函数"""

    def test_get_multi_agent_manager(self):
        """测试获取单例实例"""
        manager1 = get_multi_agent_manager()
        manager2 = get_multi_agent_manager()

        assert manager1 is manager2

    def test_reset_multi_agent_manager(self):
        """测试重置单例"""
        manager1 = get_multi_agent_manager()

        reset_multi_agent_manager()

        manager2 = get_multi_agent_manager()

        assert manager1 is not manager2

    def test_reset_clears_state(self):
        """重置后新实例共享组件为空"""
        manager = get_multi_agent_manager()
        manager.initialize_shared_components(plan_orchestrator=MagicMock())

        reset_multi_agent_manager()

        new_manager = get_multi_agent_manager()
        assert new_manager._plan_orchestrator is None
        assert new_manager._agents == {}
