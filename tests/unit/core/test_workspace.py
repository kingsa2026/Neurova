"""
工作空间测试
测试 Workspace 的各种功能，包括初始化、服务管理、生命周期等。
"""

import pytest
import sys
import os
import asyncio
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../')))

from neurova.core.workspace import Workspace


class TestWorkspace:
    """测试工作空间"""

    @pytest.fixture
    def workspace(self, tmp_path):
        """创建工作空间实例"""
        agent_id = "test-agent"
        workspace_dir = str(tmp_path / "workspace")
        return Workspace(agent_id, workspace_dir)

    def test_init(self, workspace):
        """测试初始化"""
        assert workspace is not None
        assert workspace.agent_id == "test-agent"
        assert workspace.workspace_dir.exists()
        assert workspace._started is False

    def test_workspace_dir_creation(self, tmp_path):
        """测试工作空间目录创建"""
        agent_id = "new-agent"
        workspace_dir = str(tmp_path / "new_workspace")
        
        workspace = Workspace(agent_id, workspace_dir)
        
        assert workspace.workspace_dir.exists()
        assert workspace.workspace_dir.is_dir()

    def test_agent_id(self, workspace):
        """测试代理ID"""
        assert workspace.agent_id == "test-agent"

    def test_started_property(self, workspace):
        """测试启动状态属性"""
        assert workspace.started is False
        workspace._started = True
        assert workspace.started is True

    def test_set_manager(self, workspace):
        """测试设置管理器"""
        mock_manager = MagicMock()
        workspace.set_manager(mock_manager)
        assert workspace._manager == mock_manager

    @pytest.mark.asyncio
    async def test_start(self, workspace):
        """测试启动工作空间"""
        with patch.object(workspace._service_manager, 'start_all', new_callable=AsyncMock) as mock_start:
            await workspace.start()
            mock_start.assert_called_once()
            assert workspace._started is True

    @pytest.mark.asyncio
    async def test_stop(self, workspace):
        """测试停止工作空间"""
        workspace._started = True
        
        with patch.object(workspace._service_manager, 'stop_all', new_callable=AsyncMock) as mock_stop:
            await workspace.stop()
            mock_stop.assert_called_once()
            assert workspace._started is False

    @pytest.mark.asyncio
    async def test_stop_final(self, workspace):
        """测试最终停止工作空间"""
        workspace._started = True
        
        with patch.object(workspace._service_manager, 'stop_all', new_callable=AsyncMock) as mock_stop:
            await workspace.stop(final=True)
            mock_stop.assert_called_once_with(final=True)
            assert workspace._started is False

    def test_get_reusable_services(self, workspace):
        """测试获取可复用服务"""
        with patch.object(workspace._service_manager, 'get_reusable_services', return_value={}) as mock_get:
            services = workspace.get_reusable_services()
            mock_get.assert_called_once()
            assert services == {}

    @pytest.mark.asyncio
    async def test_set_reusable_services(self, workspace):
        """测试设置可复用服务"""
        services = {"service1": MagicMock(), "service2": MagicMock()}
        
        with patch.object(workspace._service_manager, 'set_reusable', new_callable=AsyncMock) as mock_set:
            await workspace.set_reusable_services(services)
            assert mock_set.call_count == 2

    def test_memory_manager_property(self, workspace):
        """测试记忆管理器属性"""
        with patch.object(workspace._service_manager, 'services', {'memory_manager': MagicMock()}):
            manager = workspace.memory_manager
            assert manager is not None

    def test_channel_manager_property(self, workspace):
        """测试通道管理器属性"""
        with patch.object(workspace._service_manager, 'services', {'channel_manager': MagicMock()}):
            manager = workspace.channel_manager
            assert manager is not None

    def test_skill_manager_property(self, workspace):
        """测试技能管理器属性"""
        with patch.object(workspace._service_manager, 'services', {'skill_manager': MagicMock()}):
            manager = workspace.skill_manager
            assert manager is not None

    def test_project_manager_property(self, workspace):
        """测试项目管理器属性"""
        with patch.object(workspace._service_manager, 'services', {'project_manager': MagicMock()}):
            manager = workspace.project_manager
            assert manager is not None

    def test_cron_manager_property(self, workspace):
        """测试定时任务管理器属性"""
        with patch.object(workspace._service_manager, 'services', {'cron_manager': MagicMock()}):
            manager = workspace.cron_manager
            assert manager is not None

    def test_none_service_properties(self, workspace):
        """测试服务属性返回None"""
        with patch.object(workspace._service_manager, 'services', {}):
            assert workspace.memory_manager is None
            assert workspace.channel_manager is None
            assert workspace.skill_manager is None
            assert workspace.project_manager is None
            assert workspace.cron_manager is None


class TestWorkspaceServices:
    """测试工作空间服务管理"""

    @pytest.fixture
    def workspace_with_services(self, tmp_path):
        """创建带服务的工作空间"""
        agent_id = "service-agent"
        workspace_dir = str(tmp_path / "service_workspace")
        workspace = Workspace(agent_id, workspace_dir)
        
        mock_services = {
            "memory_manager": MagicMock(),
            "channel_manager": MagicMock(),
            "skill_manager": MagicMock(),
            "project_manager": MagicMock(),
            "cron_manager": MagicMock(),
        }
        
        workspace._service_manager._services = mock_services
        return workspace

    def test_access_all_services(self, workspace_with_services):
        """测试访问所有服务"""
        ws = workspace_with_services
        
        assert ws.memory_manager is not None
        assert ws.channel_manager is not None
        assert ws.skill_manager is not None
        assert ws.project_manager is not None
        assert ws.cron_manager is not None


class TestWorkspaceLifecycle:
    """测试工作空间生命周期"""

    @pytest.fixture
    def workspace(self, tmp_path):
        """创建工作空间实例"""
        agent_id = "lifecycle-agent"
        workspace_dir = str(tmp_path / "lifecycle_workspace")
        return Workspace(agent_id, workspace_dir)

    @pytest.mark.asyncio
    async def test_start_stop_cycle(self, workspace):
        """测试启动-停止循环"""
        with patch.object(workspace._service_manager, 'start_all', new_callable=AsyncMock):
            with patch.object(workspace._service_manager, 'stop_all', new_callable=AsyncMock):
                await workspace.start()
                assert workspace.started is True
                
                await workspace.stop()
                assert workspace.started is False

    @pytest.mark.asyncio
    async def test_multiple_start_stop(self, workspace):
        """测试多次启动-停止"""
        with patch.object(workspace._service_manager, 'start_all', new_callable=AsyncMock):
            with patch.object(workspace._service_manager, 'stop_all', new_callable=AsyncMock):
                for i in range(3):
                    await workspace.start()
                    assert workspace.started is True
                    
                    await workspace.stop()
                    assert workspace.started is False


class TestEdgeCases:
    """测试边界情况"""

    def test_workspace_with_existing_dir(self, tmp_path):
        """测试已存在目录的工作空间"""
        agent_id = "existing-agent"
        workspace_dir = str(tmp_path / "existing_workspace")
        
        Path(workspace_dir).mkdir(parents=True, exist_ok=True)
        (Path(workspace_dir) / "test.txt").write_text("test")
        
        workspace = Workspace(agent_id, workspace_dir)
        
        assert workspace.workspace_dir.exists()
        assert (Path(workspace_dir) / "test.txt").exists()

    def test_workspace_with_special_chars_in_id(self, tmp_path):
        """测试ID包含特殊字符的工作空间"""
        agent_id = "agent-with_special.chars"
        workspace_dir = str(tmp_path / "special_workspace")
        
        workspace = Workspace(agent_id, workspace_dir)
        
        assert workspace.agent_id == agent_id
        assert workspace.workspace_dir.exists()

    def test_workspace_with_long_id(self, tmp_path):
        """测试长ID的工作空间"""
        agent_id = "a" * 100
        workspace_dir = str(tmp_path / "long_workspace")
        
        workspace = Workspace(agent_id, workspace_dir)
        
        assert workspace.agent_id == agent_id

    def test_workspace_with_empty_id(self, tmp_path):
        """测试空ID的工作空间"""
        agent_id = ""
        workspace_dir = str(tmp_path / "empty_workspace")
        
        workspace = Workspace(agent_id, workspace_dir)
        
        assert workspace.agent_id == ""

    @pytest.mark.asyncio
    async def test_start_when_already_started(self, workspace):
        """测试已启动时再次启动"""
        workspace._started = True
        
        with patch.object(workspace._service_manager, 'start_all', new_callable=AsyncMock) as mock_start:
            await workspace.start()
            mock_start.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_when_not_started(self, workspace):
        """测试未启动时停止"""
        assert workspace._started is False
        
        with patch.object(workspace._service_manager, 'stop_all', new_callable=AsyncMock) as mock_stop:
            await workspace.stop()
            mock_stop.assert_called_once()
            assert workspace._started is False
