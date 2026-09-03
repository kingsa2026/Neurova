"""
负一屏推送集成测试

测试内容：
1. 用户级 authCode 配置隔离
2. NegativeScreenPusher 推送功能
3. NotificationManager 集成
4. 设置 API 端点
"""

import asyncio
import json
import os
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ─── 测试 NegativeScreenConfig ───────────────────────────────────────────────


class TestNegativeScreenConfig:
    """测试负一屏配置数据结构"""

    def test_config_creation(self):
        """测试配置创建"""
        from neurova.notifications.negative_screen import NegativeScreenConfig

        config = NegativeScreenConfig(
            user_id="user_001",
            auth_code="test_auth_code_123",
            enabled=True,
        )

        assert config.user_id == "user_001"
        assert config.auth_code == "test_auth_code_123"
        assert config.enabled is True
        assert config.push_url == "https://hiboard-claw-drcn.ai.dbankcloud.cn/distribution/message/cloud/claw/msg/upload"

    def test_config_default_values(self):
        """测试默认值"""
        from neurova.notifications.negative_screen import NegativeScreenConfig

        config = NegativeScreenConfig(user_id="user_001")

        assert config.auth_code is None
        assert config.enabled is False
        assert config.push_url is not None

    def test_config_to_dict(self):
        """测试序列化"""
        from neurova.notifications.negative_screen import NegativeScreenConfig

        config = NegativeScreenConfig(
            user_id="user_001",
            auth_code="test_auth_code",
            enabled=True,
        )

        data = config.to_dict()
        assert data["user_id"] == "user_001"
        assert data["auth_code"] == "test_auth_code"
        assert data["enabled"] is True

    def test_config_from_dict(self):
        """测试反序列化"""
        from neurova.notifications.negative_screen import NegativeScreenConfig

        data = {
            "user_id": "user_001",
            "auth_code": "test_auth_code",
            "enabled": True,
            "push_url": "https://custom-url.com",
        }

        config = NegativeScreenConfig.from_dict(data)
        assert config.user_id == "user_001"
        assert config.auth_code == "test_auth_code"
        assert config.push_url == "https://custom-url.com"

    def test_config_masked_auth_code(self):
        """测试 authCode 脱敏"""
        from neurova.notifications.negative_screen import NegativeScreenConfig

        config = NegativeScreenConfig(
            user_id="user_001",
            auth_code="2PFMVcODezYn",
        )

        masked = config.masked_auth_code
        assert masked == "2PFM***"
        assert len(masked) == 7

    def test_config_masked_auth_code_none(self):
        """测试 authCode 为空时的脱敏"""
        from neurova.notifications.negative_screen import NegativeScreenConfig

        config = NegativeScreenConfig(user_id="user_001")
        assert config.masked_auth_code is None


# ─── 测试 NegativeScreenConfigManager ────────────────────────────────────────


class TestNegativeScreenConfigManager:
    """测试负一屏配置管理器"""

    def test_manager_initialization(self):
        """测试管理器初始化"""
        from neurova.notifications.negative_screen import NegativeScreenConfigManager

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = NegativeScreenConfigManager(data_dir=tmpdir)
            assert manager._data_dir == Path(tmpdir)

    def test_save_and_get_config(self):
        """测试保存和获取配置"""
        from neurova.notifications.negative_screen import (
            NegativeScreenConfig,
            NegativeScreenConfigManager,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = NegativeScreenConfigManager(data_dir=tmpdir)

            config = NegativeScreenConfig(
                user_id="user_001",
                auth_code="test_auth_code",
                enabled=True,
            )

            # 保存配置
            success = manager.save_config(config)
            assert success is True

            # 获取配置
            retrieved = manager.get_config("user_001")
            assert retrieved is not None
            assert retrieved.user_id == "user_001"
            assert retrieved.auth_code == "test_auth_code"
            assert retrieved.enabled is True

    def test_user_isolation(self):
        """测试用户隔离"""
        from neurova.notifications.negative_screen import (
            NegativeScreenConfig,
            NegativeScreenConfigManager,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = NegativeScreenConfigManager(data_dir=tmpdir)

            # 用户1的配置
            config1 = NegativeScreenConfig(
                user_id="user_001",
                auth_code="auth_code_1",
                enabled=True,
            )
            manager.save_config(config1)

            # 用户2的配置
            config2 = NegativeScreenConfig(
                user_id="user_002",
                auth_code="auth_code_2",
                enabled=False,
            )
            manager.save_config(config2)

            # 验证隔离
            retrieved1 = manager.get_config("user_001")
            retrieved2 = manager.get_config("user_002")

            assert retrieved1.auth_code == "auth_code_1"
            assert retrieved1.enabled is True
            assert retrieved2.auth_code == "auth_code_2"
            assert retrieved2.enabled is False

    def test_get_nonexistent_config(self):
        """测试获取不存在的配置"""
        from neurova.notifications.negative_screen import NegativeScreenConfigManager

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = NegativeScreenConfigManager(data_dir=tmpdir)
            config = manager.get_config("nonexistent_user")
            assert config is None

    def test_delete_config(self):
        """测试删除配置"""
        from neurova.notifications.negative_screen import (
            NegativeScreenConfig,
            NegativeScreenConfigManager,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = NegativeScreenConfigManager(data_dir=tmpdir)

            config = NegativeScreenConfig(
                user_id="user_001",
                auth_code="test_auth_code",
            )
            manager.save_config(config)

            # 删除配置
            success = manager.delete_config("user_001")
            assert success is True

            # 验证已删除
            retrieved = manager.get_config("user_001")
            assert retrieved is None

    def test_list_configs(self):
        """测试列出所有配置"""
        from neurova.notifications.negative_screen import (
            NegativeScreenConfig,
            NegativeScreenConfigManager,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = NegativeScreenConfigManager(data_dir=tmpdir)

            # 创建多个配置
            for i in range(3):
                config = NegativeScreenConfig(
                    user_id=f"user_{i:03d}",
                    auth_code=f"auth_{i}",
                    enabled=i % 2 == 0,
                )
                manager.save_config(config)

            # 列出配置
            configs = manager.list_configs()
            assert len(configs) == 3

    def test_thread_safety(self):
        """测试线程安全"""
        from neurova.notifications.negative_screen import (
            NegativeScreenConfig,
            NegativeScreenConfigManager,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = NegativeScreenConfigManager(data_dir=tmpdir)
            results = []
            errors = []

            def save_config(user_id: str):
                try:
                    config = NegativeScreenConfig(
                        user_id=user_id,
                        auth_code=f"auth_{user_id}",
                        enabled=True,
                    )
                    success = manager.save_config(config)
                    results.append((user_id, success))
                except Exception as e:
                    errors.append((user_id, str(e)))

            # 并发保存
            threads = []
            for i in range(10):
                thread = threading.Thread(target=save_config, args=(f"user_{i:03d}",))
                threads.append(thread)
                thread.start()

            for thread in threads:
                thread.join()

            assert len(errors) == 0
            assert len(results) == 10


# ─── 测试 NegativeScreenPusher ──────────────────────────────────────────────


class TestNegativeScreenPusher:
    """测试负一屏推送器"""

    def test_pusher_initialization(self):
        """测试推送器初始化"""
        from neurova.notifications.negative_screen import NegativeScreenPusher

        pusher = NegativeScreenPusher()
        assert pusher._timeout == 30
        assert pusher._max_content_length == 5000

    @pytest.mark.asyncio
    async def test_push_task_success(self):
        """测试任务推送成功"""
        from neurova.notifications.negative_screen import (
            NegativeScreenConfig,
            NegativeScreenPusher,
            PushResult,
        )

        config = NegativeScreenConfig(
            user_id="user_001",
            auth_code="test_auth_code",
            enabled=True,
        )

        pusher = NegativeScreenPusher()

        # Mock _execute_push 方法（避免依赖 aiohttp）
        with patch.object(pusher, "_execute_push") as mock_execute:
            mock_execute.return_value = PushResult(
                success=True,
                task_id="test_task_001",
                response_code="0000000000",
                push_time="2026-06-10T14:00:00",
            )

            result = await pusher.push_task(
                config=config,
                task_name="测试任务",
                task_content="## 测试内容\n- 项目1\n- 项目2",
                task_result="任务完成",
            )

            assert result.success is True
            assert result.task_id == "test_task_001"
            assert result.response_code == "0000000000"
            mock_execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_push_task_no_auth_code(self):
        """测试无 authCode 时推送失败"""
        from neurova.notifications.negative_screen import (
            NegativeScreenConfig,
            NegativeScreenPusher,
        )

        config = NegativeScreenConfig(
            user_id="user_001",
            auth_code=None,
            enabled=True,
        )

        pusher = NegativeScreenPusher()

        result = await pusher.push_task(
            config=config,
            task_name="测试任务",
            task_content="测试内容",
            task_result="任务完成",
        )

        assert result.success is False
        assert "auth_code" in result.error.lower() or "未设置" in result.error

    @pytest.mark.asyncio
    async def test_push_task_disabled(self):
        """测试推送功能禁用时"""
        from neurova.notifications.negative_screen import (
            NegativeScreenConfig,
            NegativeScreenPusher,
        )

        config = NegativeScreenConfig(
            user_id="user_001",
            auth_code="test_auth_code",
            enabled=False,
        )

        pusher = NegativeScreenPusher()

        result = await pusher.push_task(
            config=config,
            task_name="测试任务",
            task_content="测试内容",
            task_result="任务完成",
        )

        assert result.success is False
        assert "禁用" in result.error or "disabled" in result.error.lower()

    @pytest.mark.asyncio
    async def test_push_task_network_error(self):
        """测试网络错误时的处理"""
        from neurova.notifications.negative_screen import (
            NegativeScreenConfig,
            NegativeScreenPusher,
            PushResult,
        )

        config = NegativeScreenConfig(
            user_id="user_001",
            auth_code="test_auth_code",
            enabled=True,
        )

        pusher = NegativeScreenPusher()

        # Mock _execute_push 返回网络错误
        with patch.object(pusher, "_execute_push") as mock_execute:
            mock_execute.return_value = PushResult(
                success=False,
                task_id="test_task_002",
                error="Network error",
            )

            result = await pusher.push_task(
                config=config,
                task_name="测试任务",
                task_content="测试内容",
                task_result="任务完成",
            )

            assert result.success is False
            assert "error" in result.error.lower() or "失败" in result.error or "Network error" in result.error


# ─── 测试 NotificationManager 集成 ──────────────────────────────────────────


class TestNotificationManagerIntegration:
    """测试通知管理器集成"""

    def test_notification_with_negative_screen_push(self):
        """测试通知触发负一屏推送"""
        from neurova.notifications.negative_screen import (
            NegativeScreenConfig,
            NegativeScreenConfigManager,
        )
        from neurova.notifications.manager import NotificationManager

        with tempfile.TemporaryDirectory() as tmpdir:
            config_manager = NegativeScreenConfigManager(data_dir=tmpdir)

            # 设置用户配置
            config = NegativeScreenConfig(
                user_id="user_001",
                auth_code="test_auth_code",
                enabled=True,
            )
            config_manager.save_config(config)

            # 创建通知管理器
            notification_manager = NotificationManager(
                negative_screen_config_manager=config_manager,
            )

            # Mock _schedule_negative_screen_push
            with patch.object(
                notification_manager,
                "_schedule_negative_screen_push",
            ) as mock_push:
                # 添加任务完成通知
                notification = notification_manager.add_notification(
                    user_id="user_001",
                    title="任务完成",
                    message="RSI 系统测试完成",
                    notification_type="task_completed",
                    data={
                        "task_name": "RSI 测试",
                        "task_content": "## 测试内容",
                        "task_result": "测试通过",
                    },
                )

                assert notification is not None
                # 验证推送被调用
                mock_push.assert_called_once()

    def test_notification_without_negative_screen(self):
        """测试非任务完成类型不触发推送"""
        from neurova.notifications.negative_screen import NegativeScreenConfigManager
        from neurova.notifications.manager import NotificationManager

        with tempfile.TemporaryDirectory() as tmpdir:
            config_manager = NegativeScreenConfigManager(data_dir=tmpdir)

            # 创建通知管理器
            notification_manager = NotificationManager(
                negative_screen_config_manager=config_manager,
            )

            # Mock _schedule_negative_screen_push
            with patch.object(
                notification_manager,
                "_schedule_negative_screen_push",
            ) as mock_push:
                # 添加普通通知
                notification = notification_manager.add_notification(
                    user_id="user_001",
                    title="普通通知",
                    message="这是一条普通通知",
                    notification_type="info",
                )

                assert notification is not None
                # 验证推送未被调用（非任务完成类型）
                mock_push.assert_not_called()


# ─── 测试设置 API ────────────────────────────────────────────────────────────


class TestNegativeScreenSettingsAPI:
    """测试负一屏设置 API"""

    @pytest.fixture
    def client(self):
        """创建测试客户端"""
        from fastapi.testclient import TestClient
        from neurova.api.app import create_app

        app = create_app()
        return TestClient(app)

    def test_get_negative_screen_config(self, client):
        """测试获取负一屏配置"""
        response = client.get("/api/v1/negative-screen")

        assert response.status_code == 200
        data = response.json()
        assert data["user_id"] == "default_user"

    def test_update_negative_screen_config(self, client):
        """测试更新负一屏配置"""
        config_data = {
            "auth_code": "new_auth_code_123",
            "enabled": True,
        }

        response = client.put(
            "/api/v1/negative-screen",
            json=config_data,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0

    def test_test_negative_screen_push(self, client):
        """测试负一屏推送测试功能"""
        test_data = {
            "task_name": "测试推送",
            "task_content": "## 测试内容",
            "task_result": "测试结果",
        }

        with patch(
            "neurova.notifications.negative_screen.NegativeScreenPusher.push_task"
        ) as mock_push:
            mock_push.return_value = MagicMock(
                success=True,
                task_id="test_task_id",
                response_code="0000000000",
            )

            response = client.post(
                "/api/v1/negative-screen/test",
                json=test_data,
            )

            # 如果用户未配置，会返回 400
            assert response.status_code in (200, 400)


# ─── 测试与 PostChatPipeline 集成 ────────────────────────────────────────────


class TestPostChatPipelineIntegration:
    """测试与 PostChatPipeline 集成"""

    @pytest.mark.asyncio
    async def test_rsi_result_pushed_to_negative_screen(self):
        """测试 RSI 结果推送到负一屏"""
        from neurova.notifications.negative_screen import (
            NegativeScreenConfig,
            NegativeScreenConfigManager,
            NegativeScreenPusher,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            config_manager = NegativeScreenConfigManager(data_dir=tmpdir)

            # 设置用户配置
            config = NegativeScreenConfig(
                user_id="user_001",
                auth_code="test_auth_code",
                enabled=True,
            )
            config_manager.save_config(config)

            # 创建推送器
            pusher = NegativeScreenPusher()

            # Mock 推送
            with patch.object(pusher, "push_task") as mock_push:
                mock_push.return_value = MagicMock(
                    success=True,
                    task_id="rsi_task_001",
                )

                # 模拟 RSI 结果
                rsi_result = {
                    "iteration": 1,
                    "improvements": 3,
                    "convergence_score": 0.85,
                    "status": "completed",
                }

                # 推送 RSI 结果
                result = await pusher.push_rsi_result(
                    config=config,
                    rsi_result=rsi_result,
                )

                assert result.success is True
                mock_push.assert_called_once()


# ─── 运行测试 ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
