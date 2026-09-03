"""
测试共享组记忆系统

验证 ShareGroupManager 和 MemoryStorage 的共享组过滤功能。
"""

import json
import os
import tempfile
import threading
import pytest

from neurova.cognitive_layers.memory_layer.share_group import (
    ShareGroup,
    ShareGroupManager,
    get_share_group_manager,
    reset_share_group_manager,
)
from neurova.cognitive_layers.memory_layer.storage import MemoryStorage, MemoryRecord
from neurova.cognitive_layers.memory_layer.isolation import IsolationContext


class TestShareGroupManager:
    """测试 ShareGroupManager"""

    def setup_method(self):
        """每个测试前重置单例"""
        reset_share_group_manager()
        self.temp_dir = tempfile.mkdtemp()
        self.storage_path = os.path.join(self.temp_dir, "test_groups.json")

    def teardown_method(self):
        """清理临时文件"""
        reset_share_group_manager()
        if os.path.exists(self.storage_path):
            os.remove(self.storage_path)

    def test_create_group(self):
        """测试创建共享组"""
        manager = ShareGroupManager(storage_path=self.storage_path)
        group = manager.create_group(
            name="测试组",
            agent_ids=["agent_1", "agent_2"],
            description="测试描述"
        )
        
        assert group.name == "测试组"
        assert group.description == "测试描述"
        assert set(group.agent_ids) == {"agent_1", "agent_2"}
        assert group.group_id is not None

    def test_list_groups(self):
        """测试列出所有共享组"""
        manager = ShareGroupManager(storage_path=self.storage_path)
        manager.create_group(name="组A", agent_ids=["a1", "a2"])
        manager.create_group(name="组B", agent_ids=["b1", "b2"])
        
        groups = manager.list_groups()
        assert len(groups) == 2

    def test_get_group(self):
        """测试获取共享组"""
        manager = ShareGroupManager(storage_path=self.storage_path)
        group = manager.create_group(name="测试组", agent_ids=["a1", "a2"])
        
        retrieved = manager.get_group(group.group_id)
        assert retrieved is not None
        assert retrieved.name == "测试组"

    def test_delete_group(self):
        """测试删除共享组"""
        manager = ShareGroupManager(storage_path=self.storage_path)
        group = manager.create_group(name="测试组", agent_ids=["a1", "a2"])
        
        assert manager.delete_group(group.group_id) is True
        assert manager.get_group(group.group_id) is None
        assert len(manager.list_groups()) == 0

    def test_add_agent_to_group(self):
        """测试将 Agent 添加到共享组"""
        manager = ShareGroupManager(storage_path=self.storage_path)
        group = manager.create_group(name="测试组", agent_ids=["a1"])
        
        success = manager.add_agent_to_group(group.group_id, "a2")
        assert success is True
        
        agents = manager.get_agents_in_group(group.group_id)
        assert set(agents) == {"a1", "a2"}

    def test_remove_agent_from_group(self):
        """测试从共享组移除 Agent"""
        manager = ShareGroupManager(storage_path=self.storage_path)
        group = manager.create_group(name="测试组", agent_ids=["a1", "a2"])
        
        success = manager.remove_agent_from_group(group.group_id, "a2")
        assert success is True
        
        agents = manager.get_agents_in_group(group.group_id)
        assert agents == ["a1"]

    def test_get_groups_for_agent(self):
        """测试获取 Agent 所属的所有共享组"""
        manager = ShareGroupManager(storage_path=self.storage_path)
        manager.create_group(name="组A", agent_ids=["a1", "a2"])
        manager.create_group(name="组B", agent_ids=["a1", "a3"])
        
        groups = manager.get_groups_for_agent("a1")
        assert len(groups) == 2
        
        groups_a2 = manager.get_groups_for_agent("a2")
        assert len(groups_a2) == 1

    def test_get_shared_agent_ids(self):
        """测试获取与指定 Agent 共享记忆的所有 Agent"""
        manager = ShareGroupManager(storage_path=self.storage_path)
        manager.create_group(name="组A", agent_ids=["a1", "a2"])
        manager.create_group(name="组B", agent_ids=["a1", "a3"])
        
        shared = manager.get_shared_agent_ids("a1")
        assert shared == {"a1", "a2", "a3"}

    def test_are_agents_shared(self):
        """测试检查两个 Agent 是否在同一共享组中"""
        manager = ShareGroupManager(storage_path=self.storage_path)
        manager.create_group(name="组A", agent_ids=["a1", "a2"])
        
        assert manager.are_agents_shared("a1", "a2") is True
        assert manager.are_agents_shared("a1", "a3") is False

    def test_persistence(self):
        """测试持久化"""
        manager = ShareGroupManager(storage_path=self.storage_path)
        manager.create_group(name="测试组", agent_ids=["a1", "a2"])
        
        # 重新加载
        manager2 = ShareGroupManager(storage_path=self.storage_path)
        groups = manager2.list_groups()
        assert len(groups) == 1
        assert groups[0].name == "测试组"


class TestMemoryStorageShareGroup:
    """测试 MemoryStorage 的共享组过滤"""

    def setup_method(self):
        """每个测试前初始化"""
        self.temp_dir = tempfile.mkdtemp()
        self.storage = MemoryStorage(self.temp_dir)
        self.groups_path = os.path.join(self.temp_dir, "share_groups.json")
        reset_share_group_manager()
        # 使用全局单例，确保 _in_same_share_group 使用同一实例
        self.manager = get_share_group_manager(storage_path=self.groups_path)

    def teardown_method(self):
        """清理"""
        reset_share_group_manager()
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _save_memory(self, agent_id: str, content: str, shared: bool = False) -> str:
        """保存记忆"""
        ctx = IsolationContext(agent_id=agent_id, shared=shared)
        return self.storage.save(
            content=content,
            memory_type="episodic",
            owner="test",
            isolation_context=ctx,
        )

    def test_same_agent_access(self):
        """同一 Agent 可以访问自己的记忆"""
        self._save_memory("agent_1", "记忆1")
        
        ctx = IsolationContext(agent_id="agent_1")
        results = self.storage.query(isolation_context=ctx)
        assert len(results) == 1
        assert results[0]["content"] == "记忆1"

    def test_different_agent_no_access(self):
        """不同 Agent 无法访问非共享记忆"""
        self._save_memory("agent_1", "记忆1")
        
        ctx = IsolationContext(agent_id="agent_2")
        results = self.storage.query(isolation_context=ctx)
        assert len(results) == 0

    def test_shared_memory_access(self):
        """共享记忆可以被任何 Agent 访问"""
        self._save_memory("agent_1", "共享记忆", shared=True)
        
        ctx = IsolationContext(agent_id="agent_2")
        results = self.storage.query(isolation_context=ctx)
        assert len(results) == 1
        assert results[0]["content"] == "共享记忆"

    def test_share_group_access(self):
        """同一共享组的 Agent 可以访问彼此的记忆"""
        # 创建共享组
        self.manager.create_group(name="测试组", agent_ids=["agent_1", "agent_2"])
        
        # agent_1 保存记忆
        self._save_memory("agent_1", "组内记忆")
        
        # agent_2 通过共享组访问
        ctx = IsolationContext(agent_id="agent_2")
        results = self.storage.query(isolation_context=ctx)
        assert len(results) == 1
        assert results[0]["content"] == "组内记忆"

    def test_share_group_no_access_outside(self):
        """不在同一共享组的 Agent 无法访问"""
        self.manager.create_group(name="组A", agent_ids=["agent_1", "agent_2"])
        
        self._save_memory("agent_1", "组内记忆")
        
        # agent_3 不在组中
        ctx = IsolationContext(agent_id="agent_3")
        results = self.storage.query(isolation_context=ctx)
        assert len(results) == 0

    def test_multiple_groups(self):
        """多个共享组的测试"""
        self.manager.create_group(name="组A", agent_ids=["agent_1", "agent_2"])
        self.manager.create_group(name="组B", agent_ids=["agent_3", "agent_4"])
        
        self._save_memory("agent_1", "组A记忆")
        self._save_memory("agent_3", "组B记忆")
        
        # agent_2 只能访问组A的记忆
        ctx = IsolationContext(agent_id="agent_2")
        results = self.storage.query(isolation_context=ctx)
        assert len(results) == 1
        assert results[0]["content"] == "组A记忆"
        
        # agent_4 只能访问组B的记忆
        ctx = IsolationContext(agent_id="agent_4")
        results = self.storage.query(isolation_context=ctx)
        assert len(results) == 1
        assert results[0]["content"] == "组B记忆"

    def test_agent_in_multiple_groups(self):
        """Agent 在多个共享组中的测试"""
        self.manager.create_group(name="组A", agent_ids=["agent_1", "agent_2"])
        self.manager.create_group(name="组B", agent_ids=["agent_1", "agent_3"])
        
        self._save_memory("agent_2", "组A记忆")
        self._save_memory("agent_3", "组B记忆")
        
        # agent_1 可以访问两个组的记忆
        ctx = IsolationContext(agent_id="agent_1")
        results = self.storage.query(isolation_context=ctx)
        assert len(results) == 2
        contents = {r["content"] for r in results}
        assert contents == {"组A记忆", "组B记忆"}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])