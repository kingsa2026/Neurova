"""
Neurflow agent_manager.py 测试 — TDD 垂直切片 9

测试团队 Agent 管理器功能：
1. 创建临时团队 Agent
2. 获取 Agent
3. 列出 Agent（按 flow_id 过滤，包含/不包含归档）
4. 归档 Agent
5. 恢复 Agent
6. 删除 Agent
7. 工厂函数（单例）
"""
import pytest
import time
from unittest.mock import patch, MagicMock
from typing import Dict, List, Optional, Any

# 导入待测模块（尚未存在，测试将失败）
from neurova.collaboration.neurflow.agent_manager import (
    NeurflowAgentManager,
    get_agent_manager,
    reset_agent_manager,
)


class TestNeurflowAgentManager:
    """测试 NeurflowAgentManager 核心功能"""

    def test_create_agent_basic(self):
        """测试创建基本的临时 Agent"""
        manager = NeurflowAgentManager()
        agent = manager.create_agent(
            name="测试 Agent",
            role="coder",
            config={"model": "gpt-4"},
            flow_id="flow_1"
        )
        
        assert agent.agent_id.startswith("neurflow_")
        assert agent.name == "测试 Agent"
        assert agent.role == "coder"
        assert agent.config == {"model": "gpt-4"}
        assert agent.flow_id == "flow_1"
        assert agent.status == "active"
        assert agent.created_at > 0
        assert agent.archived_at is None

    def test_create_agent_with_defaults(self):
        """测试创建 Agent 时的默认值"""
        manager = NeurflowAgentManager()
        agent = manager.create_agent(name="默认 Agent", role="assistant")
        
        assert agent.config == {}
        assert agent.flow_id is None
        assert agent.capabilities == []
        assert agent.metadata == {}

    def test_create_multiple_agents_unique_ids(self):
        """测试创建多个 Agent 时 ID 唯一"""
        manager = NeurflowAgentManager()
        agent1 = manager.create_agent(name="Agent1", role="coder")
        agent2 = manager.create_agent(name="Agent2", role="reviewer")
        
        assert agent1.agent_id != agent2.agent_id
        assert len(manager.list_agents()) == 2

    def test_get_agent_existing(self):
        """测试获取已存在的 Agent"""
        manager = NeurflowAgentManager()
        agent = manager.create_agent(name="测试 Agent", role="coder")
        retrieved = manager.get_agent(agent.agent_id)
        
        assert retrieved is not None
        assert retrieved.agent_id == agent.agent_id
        assert retrieved.name == "测试 Agent"

    def test_get_agent_nonexistent(self):
        """测试获取不存在的 Agent"""
        manager = NeurflowAgentManager()
        retrieved = manager.get_agent("nonexistent_id")
        
        assert retrieved is None

    def test_list_agents_all(self):
        """测试列出所有 Agent"""
        manager = NeurflowAgentManager()
        manager.create_agent(name="Agent1", role="coder")
        manager.create_agent(name="Agent2", role="reviewer")
        manager.create_agent(name="Agent3", role="tester")
        
        agents = manager.list_agents()
        assert len(agents) == 3

    def test_list_agents_by_flow_id(self):
        """测试按 flow_id 过滤 Agent"""
        manager = NeurflowAgentManager()
        manager.create_agent(name="Agent1", role="coder", flow_id="flow_1")
        manager.create_agent(name="Agent2", role="reviewer", flow_id="flow_1")
        manager.create_agent(name="Agent3", role="tester", flow_id="flow_2")
        
        agents = manager.list_agents(flow_id="flow_1")
        assert len(agents) == 2
        assert all(a.flow_id == "flow_1" for a in agents)

    def test_list_agents_include_archived(self):
        """测试列出 Agent 时包含归档的"""
        manager = NeurflowAgentManager()
        agent1 = manager.create_agent(name="Active Agent", role="coder")
        agent2 = manager.create_agent(name="To Archive Agent", role="reviewer")
        manager.archive_agent(agent2.agent_id)
        
        # 默认不包含归档
        active_agents = manager.list_agents()
        assert len(active_agents) == 1
        assert active_agents[0].agent_id == agent1.agent_id
        
        # 包含归档
        all_agents = manager.list_agents(include_archived=True)
        assert len(all_agents) == 2

    def test_archive_agent_success(self):
        """测试成功归档 Agent"""
        manager = NeurflowAgentManager()
        agent = manager.create_agent(name="To Archive", role="coder")
        
        result = manager.archive_agent(agent.agent_id)
        assert result is True
        
        # 验证 Agent 状态
        archived = manager.get_agent(agent.agent_id)
        assert archived is not None
        assert archived.status == "archived"
        assert archived.archived_at is not None
        assert archived.archived_at > 0

    def test_archive_agent_nonexistent(self):
        """测试归档不存在的 Agent"""
        manager = NeurflowAgentManager()
        result = manager.archive_agent("nonexistent_id")
        
        assert result is False

    def test_archive_agent_already_archived(self):
        """测试归档已经归档的 Agent"""
        manager = NeurflowAgentManager()
        agent = manager.create_agent(name="To Archive", role="coder")
        manager.archive_agent(agent.agent_id)
        
        # 再次归档应该失败
        result = manager.archive_agent(agent.agent_id)
        assert result is False

    def test_restore_agent_success(self):
        """测试成功恢复归档的 Agent"""
        manager = NeurflowAgentManager()
        agent = manager.create_agent(name="To Restore", role="coder")
        manager.archive_agent(agent.agent_id)
        
        result = manager.restore_agent(agent.agent_id)
        assert result is True
        
        # 验证 Agent 状态
        restored = manager.get_agent(agent.agent_id)
        assert restored is not None
        assert restored.status == "active"
        assert restored.archived_at is None

    def test_restore_agent_nonexistent(self):
        """测试恢复不存在的 Agent"""
        manager = NeurflowAgentManager()
        result = manager.restore_agent("nonexistent_id")
        
        assert result is False

    def test_restore_agent_not_archived(self):
        """测试恢复未归档的 Agent"""
        manager = NeurflowAgentManager()
        agent = manager.create_agent(name="Active Agent", role="coder")
        
        result = manager.restore_agent(agent.agent_id)
        assert result is False

    def test_delete_agent_active(self):
        """测试删除活跃的 Agent"""
        manager = NeurflowAgentManager()
        agent = manager.create_agent(name="To Delete", role="coder")
        
        result = manager.delete_agent(agent.agent_id)
        assert result is True
        
        # 验证 Agent 已被删除
        deleted = manager.get_agent(agent.agent_id)
        assert deleted is None

    def test_delete_agent_archived(self):
        """测试删除归档的 Agent"""
        manager = NeurflowAgentManager()
        agent = manager.create_agent(name="To Delete", role="coder")
        manager.archive_agent(agent.agent_id)
        
        result = manager.delete_agent(agent.agent_id)
        assert result is True
        
        # 验证 Agent 已被删除
        deleted = manager.get_agent(agent.agent_id)
        assert deleted is None

    def test_delete_agent_nonexistent(self):
        """测试删除不存在的 Agent"""
        manager = NeurflowAgentManager()
        result = manager.delete_agent("nonexistent_id")
        
        assert result is False


class TestAgentManagerSingleton:
    """测试 Agent 管理器单例模式"""

    def test_get_agent_manager_singleton(self):
        """测试 get_agent_manager 返回单例"""
        manager1 = get_agent_manager()
        manager2 = get_agent_manager()
        
        assert manager1 is manager2

    def test_reset_agent_manager(self):
        """测试重置单例"""
        manager1 = get_agent_manager()
        reset_agent_manager()
        manager2 = get_agent_manager()
        
        assert manager1 is not manager2


class TestAgentManagerThreadSafety:
    """测试 Agent 管理器线程安全"""

    def test_concurrent_create_agents(self):
        """测试并发创建 Agent"""
        import threading
        
        manager = NeurflowAgentManager()
        agents = []
        
        def create_agent(i):
            agent = manager.create_agent(name=f"Agent_{i}", role="coder")
            agents.append(agent)
        
        threads = [threading.Thread(target=create_agent, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        assert len(agents) == 10
        assert len(manager.list_agents()) == 10
        
        # 验证所有 ID 唯一
        ids = [a.agent_id for a in agents]
        assert len(set(ids)) == 10

    def test_concurrent_archive_restore(self):
        """测试并发归档和恢复"""
        import threading
        
        manager = NeurflowAgentManager()
        agent = manager.create_agent(name="Test Agent", role="coder")
        
        def archive():
            manager.archive_agent(agent.agent_id)
        
        def restore():
            manager.restore_agent(agent.agent_id)
        
        # 多次归档和恢复
        for _ in range(5):
            t1 = threading.Thread(target=archive)
            t2 = threading.Thread(target=restore)
            t1.start()
            t2.start()
            t1.join()
            t2.join()
        
        # 最终状态应该是 active 或 archived，但不应抛出异常
        final = manager.get_agent(agent.agent_id)
        assert final is not None
        assert final.status in ["active", "archived"]


class TestAgentInfo:
    """测试 AgentInfo 数据类"""

    def test_agent_info_defaults(self):
        """测试 AgentInfo 默认值"""
        from neurova.collaboration.neurflow.models import AgentInfo
        
        agent = AgentInfo(
            agent_id="test_id",
            name="Test Agent",
            role="coder"
        )
        
        assert agent.agent_id == "test_id"
        assert agent.name == "Test Agent"
        assert agent.role == "coder"
        assert agent.config == {}
        assert agent.flow_id is None
        assert agent.created_at == 0.0
        assert agent.archived_at is None
        assert agent.status == "active"
        assert agent.capabilities == []
        assert agent.metadata == {}

    def test_agent_info_with_all_fields(self):
        """测试 AgentInfo 所有字段"""
        from neurova.collaboration.neurflow.models import AgentInfo
        
        agent = AgentInfo(
            agent_id="test_id",
            name="Test Agent",
            role="coder",
            config={"model": "gpt-4"},
            flow_id="flow_1",
            created_at=1234567890.0,
            archived_at=1234567899.0,
            status="archived",
            capabilities=["code", "review"],
            metadata={"source": "test"}
        )
        
        assert agent.config == {"model": "gpt-4"}
        assert agent.flow_id == "flow_1"
        assert agent.created_at == 1234567890.0
        assert agent.archived_at == 1234567899.0
        assert agent.status == "archived"
        assert agent.capabilities == ["code", "review"]
        assert agent.metadata == {"source": "test"}