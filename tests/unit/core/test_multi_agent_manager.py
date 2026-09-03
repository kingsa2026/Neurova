"""
测试多Agent管理器
"""
import pytest
import asyncio
import json
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock
from neurova.core.multi_agent_manager import (
    NeurovaAgent,
    MultiAgentManager,
    get_multi_agent_manager,
    reset_multi_agent_manager,
)


class TestNeurovaAgent:
    """测试NeurovaAgent数据类"""
    
    def test_create_neurova_agent(self):
        """测试创建Agent"""
        agent = NeurovaAgent(
            agent_id="test_agent",
            persona="test persona",
            constitution="test constitution",
        )
        
        assert agent.agent_id == "test_agent"
        assert agent.persona == "test persona"
        assert agent.constitution == "test constitution"
        assert agent.workspace is None
        assert agent.memory_db_path == ""
        assert agent.workspace_dir == ""
        assert agent.is_initialized is False
    
    def test_neurova_agent_is_initialized(self):
        """测试Agent初始化状态"""
        agent = NeurovaAgent(agent_id="test_agent")
        
        assert agent.is_initialized is False
        
        # 模拟workspace
        mock_workspace = MagicMock()
        mock_workspace.started = False
        agent.workspace = mock_workspace
        assert agent.is_initialized is False
        
        mock_workspace.started = True
        assert agent.is_initialized is True
    
    def test_neurova_agent_to_dict(self):
        """测试转换为字典"""
        agent = NeurovaAgent(
            agent_id="test_agent",
            persona="test persona",
            constitution="test constitution",
        )
        
        data = agent.to_dict()
        
        assert data["agent_id"] == "test_agent"
        assert data["persona"] == "test persona"
        assert data["constitution"] == "test constitution"
        assert data["is_initialized"] is False
        assert "created_at" in data
        assert "last_active" in data


class TestMultiAgentManager:
    """测试MultiAgentManager类"""
    
    def test_init(self):
        """测试初始化"""
        manager = MultiAgentManager()
        
        assert manager.agents == {}
        assert manager.shared_cerebellum is None
        assert manager.shared_brainstem is None
        assert manager._lock is not None
        assert manager._initialized is False
    
    def test_get_workspace_dir(self):
        """测试获取工作区目录"""
        manager = MultiAgentManager()
        manager.set_base_workspace_dir("/tmp/test_agents")
        
        workspace_dir = manager.get_workspace_dir("agent1")
        
        assert "agent1" in str(workspace_dir)
        assert "workspace" in str(workspace_dir)
    
    @pytest.mark.asyncio
    async def test_initialize_shared_components(self):
        """测试初始化共享组件"""
        manager = MultiAgentManager()
        
        mock_event_bus = MagicMock()
        mock_service_manager = MagicMock()
        mock_provider_manager = MagicMock()
        
        await manager.initialize_shared_components(
            event_bus=mock_event_bus,
            service_manager=mock_service_manager,
            provider_manager=mock_provider_manager,
        )
        
        assert manager._initialized is True
        assert manager.event_bus == mock_event_bus
        assert manager.service_manager == mock_service_manager
        assert manager.provider_manager == mock_provider_manager
        assert manager.shared_cerebellum is not None
        assert manager.shared_brainstem is not None
    
    @pytest.mark.asyncio
    async def test_initialize_shared_components_twice(self):
        """测试重复初始化"""
        manager = MultiAgentManager()
        
        await manager.initialize_shared_components()
        await manager.initialize_shared_components()
        
        assert manager._initialized is True
    
    def test_list_agents(self):
        """测试列出Agent"""
        manager = MultiAgentManager()
        
        agents = manager.list_agents()
        
        assert agents == []
    
    def test_is_agent_loaded(self):
        """测试检查Agent是否加载"""
        manager = MultiAgentManager()
        
        assert manager.is_agent_loaded("agent1") is False
    
    def test_get_agent_info_nonexistent(self):
        """测试获取不存在的Agent信息"""
        manager = MultiAgentManager()
        
        info = manager.get_agent_info("nonexistent")
        
        assert info is None
    
    def test_list_agents_info(self):
        """测试列出所有Agent信息"""
        manager = MultiAgentManager()
        
        infos = manager.list_agents_info()
        
        assert infos == []
    
    @pytest.mark.asyncio
    async def test_execute_with_shared_cerebellum_not_initialized(self):
        """测试未初始化时执行"""
        manager = MultiAgentManager()
        
        with pytest.raises(RuntimeError, match="共享组件未初始化"):
            await manager.execute_with_shared_cerebellum(
                agent_id="test_agent",
                input_context={"user_input": "test"},
            )
    
    @pytest.mark.asyncio
    async def test_start_agent_not_initialized(self):
        """测试未初始化时启动Agent"""
        manager = MultiAgentManager()
        
        with pytest.raises(Exception):
            agent = await manager.start_agent("test_agent")
    
    @pytest.mark.asyncio
    async def test_stop_agent_nonexistent(self):
        """测试停止不存在的Agent"""
        manager = MultiAgentManager()
        
        await manager.stop_agent("nonexistent")
        
        assert "nonexistent" not in manager.agents
    
    @pytest.mark.asyncio
    async def test_stop_all(self):
        """测试停止所有Agent"""
        manager = MultiAgentManager()
        
        await manager.stop_all()
        
        assert len(manager.agents) == 0


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
    
    @pytest.mark.asyncio
    async def test_reset_with_running_agents(self):
        """测试重置有运行中Agent的单例"""
        manager = get_multi_agent_manager()
        await manager.initialize_shared_components()
        
        reset_multi_agent_manager()
        
        new_manager = get_multi_agent_manager()
        assert new_manager._initialized is False
