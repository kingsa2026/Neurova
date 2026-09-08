"""
工作空间测试（对齐 neurova/core/workspace.py 真实契约）
测试 Workspace 的初始化、管理器装配、生命周期、可复用服务等。
"""

import pytest
from pathlib import Path
from unittest.mock import MagicMock

from neurova.core.workspace import (
    Workspace,
    create_workspace,
    get_workspace,
    list_workspaces,
    remove_workspace,
    reset_workspaces,
)


@pytest.fixture(autouse=True)
def _isolated_global_workspaces():
    """隔离模块级全局工作空间注册表"""
    reset_workspaces()
    yield
    reset_workspaces()


def _make_workspace(tmp_path, workspace_id="test-agent", **kwargs):
    return Workspace(workspace_id, tmp_path / "workspace", **kwargs)


class TestWorkspace:
    """测试工作空间"""

    def test_init(self, tmp_path):
        """测试初始化（契约：Workspace(workspace_id, data_dir, config)）"""
        ws = _make_workspace(tmp_path, workspace_id="test-agent")

        assert ws is not None
        assert ws.workspace_id == "test-agent"
        assert ws.data_dir.exists()
        assert ws.started is False

    def test_workspace_dir_creation(self, tmp_path):
        """测试工作空间目录自动创建"""
        ws = Workspace("new-agent", tmp_path / "new_workspace")

        assert ws.data_dir.exists()
        assert ws.data_dir.is_dir()

    def test_workspace_id(self, tmp_path):
        """测试工作空间ID"""
        ws = _make_workspace(tmp_path, workspace_id="test-agent")

        assert ws.workspace_id == "test-agent"

    def test_config_property(self, tmp_path):
        """测试配置属性"""
        config = {"key": "value"}
        ws = Workspace("test-agent", tmp_path / "workspace", config=config)

        assert ws.config == config

    def test_started_property(self, tmp_path):
        """测试启动状态属性"""
        ws = _make_workspace(tmp_path)

        assert ws.started is False

    def test_set_manager_known_name(self, tmp_path):
        """测试按名称设置已知管理器"""
        ws = _make_workspace(tmp_path)
        mock_manager = MagicMock()

        ws.set_manager("memory", mock_manager)

        assert ws.memory_manager is mock_manager

    def test_set_manager_custom_name(self, tmp_path):
        """未知管理器名称落入可复用服务"""
        ws = _make_workspace(tmp_path)
        mock_manager = MagicMock()

        ws.set_manager("custom_thing", mock_manager)

        assert ws.get_reusable_services() == {"custom_thing": mock_manager}

    def test_start(self, tmp_path):
        """测试启动工作空间（同步方法，启动已装配的管理器）"""
        ws = _make_workspace(tmp_path)
        memory = MagicMock()
        channel = MagicMock()
        ws.set_manager("memory", memory)
        ws.set_manager("channel", channel)

        success = ws.start()

        assert success is True
        assert ws.started is True
        memory.start.assert_called_once()
        channel.start.assert_called_once()

    def test_stop(self, tmp_path):
        """测试停止工作空间（同步方法，反序停止）"""
        ws = _make_workspace(tmp_path)
        memory = MagicMock()
        ws.set_manager("memory", memory)
        ws.start()

        success = ws.stop()

        assert success is True
        assert ws.started is False
        memory.stop.assert_called_once()

    def test_start_idempotent(self, tmp_path):
        """测试已启动时再次启动不重复触发管理器"""
        ws = _make_workspace(tmp_path)
        memory = MagicMock()
        ws.set_manager("memory", memory)

        assert ws.start() is True
        assert ws.start() is True
        memory.start.assert_called_once()

    def test_stop_when_not_started(self, tmp_path):
        """测试未启动时停止是安全的 no-op"""
        ws = _make_workspace(tmp_path)
        memory = MagicMock()
        ws.set_manager("memory", memory)

        assert ws.stop() is True
        memory.stop.assert_not_called()

    def test_reusable_services_roundtrip(self, tmp_path):
        """测试可复用服务存取"""
        ws = _make_workspace(tmp_path)
        services = {"service1": MagicMock(), "service2": MagicMock()}

        ws.set_reusable_services(services)

        assert ws.get_reusable_services() == services

    def test_manager_properties_default_none(self, tmp_path):
        """测试服务属性默认返回 None"""
        ws = _make_workspace(tmp_path)

        assert ws.memory_manager is None
        assert ws.channel_manager is None
        assert ws.skill_manager is None
        assert ws.project_manager is None
        assert ws.cron_manager is None

    def test_get_status(self, tmp_path):
        """测试状态字典键面"""
        ws = _make_workspace(tmp_path, workspace_id="status-agent")
        ws.set_manager("memory", MagicMock())
        ws.start()

        status = ws.get_status()

        assert status["workspace_id"] == "status-agent"
        assert status["started"] is True
        assert status["managers"]["memory"] is True
        assert status["managers"]["skill"] is False


class TestWorkspaceLifecycle:
    """测试工作空间生命周期"""

    def test_start_stop_cycle(self, tmp_path):
        """测试启动-停止循环"""
        ws = _make_workspace(tmp_path, workspace_id="lifecycle-agent")

        assert ws.start() is True
        assert ws.started is True

        assert ws.stop() is True
        assert ws.started is False

    def test_multiple_start_stop(self, tmp_path):
        """测试多次启动-停止"""
        ws = _make_workspace(tmp_path, workspace_id="lifecycle-agent")
        memory = MagicMock()
        ws.set_manager("memory", memory)

        for _ in range(3):
            assert ws.start() is True
            assert ws.started is True

            assert ws.stop() is True
            assert ws.started is False

        # 每轮 start 都重新拉起管理器
        assert memory.start.call_count == 3
        assert memory.stop.call_count == 3


class TestGlobalRegistry:
    """测试全局工作空间注册函数族"""

    def test_create_and_get(self, tmp_path):
        """创建后可按 ID 取回"""
        ws = create_workspace("ws-1", tmp_path / "ws1")

        assert get_workspace("ws-1") is ws
        assert list_workspaces() == ["ws-1"]

    def test_create_duplicate_raises(self, tmp_path):
        """重复创建同 ID 抛 ValueError"""
        create_workspace("ws-1", tmp_path / "ws1")

        with pytest.raises(ValueError):
            create_workspace("ws-1", tmp_path / "ws1b")

    def test_remove_workspace(self, tmp_path):
        """移除工作空间并停止它"""
        ws = create_workspace("ws-1", tmp_path / "ws1")
        ws.start()

        assert remove_workspace("ws-1") is True
        assert get_workspace("ws-1") is None
        assert ws.started is False
        assert remove_workspace("ws-1") is False

    def test_list_workspaces(self, tmp_path):
        """列出所有工作空间"""
        create_workspace("ws-a", tmp_path / "wsa")
        create_workspace("ws-b", tmp_path / "wsb")

        assert sorted(list_workspaces()) == ["ws-a", "ws-b"]


class TestEdgeCases:
    """测试边界情况"""

    def test_workspace_with_existing_dir(self, tmp_path):
        """测试已存在目录的工作空间"""
        workspace_dir = tmp_path / "existing_workspace"
        workspace_dir.mkdir(parents=True, exist_ok=True)
        (workspace_dir / "test.txt").write_text("test")

        ws = Workspace("existing-agent", workspace_dir)

        assert ws.data_dir.exists()
        assert (workspace_dir / "test.txt").exists()

    def test_workspace_with_special_chars_in_id(self, tmp_path):
        """测试ID包含特殊字符的工作空间"""
        ws = Workspace("agent-with_special.chars", tmp_path / "special_workspace")

        assert ws.workspace_id == "agent-with_special.chars"
        assert ws.data_dir.exists()

    def test_workspace_with_long_id(self, tmp_path):
        """测试长ID的工作空间"""
        long_id = "a" * 100
        ws = Workspace(long_id, tmp_path / "long_workspace")

        assert ws.workspace_id == long_id

    def test_workspace_with_empty_id(self, tmp_path):
        """测试空ID的工作空间"""
        ws = Workspace("", tmp_path / "empty_workspace")

        assert ws.workspace_id == ""
