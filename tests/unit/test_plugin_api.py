"""
插件管理 API 单元测试

测试插件管理 API 端点的功能。
"""

import sys
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI, APIRouter, Request
from fastapi.responses import JSONResponse
from neurova.interfaces.api_standard import APIError, ErrorCodes

# 添加项目路径
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))


class TestPluginAPI:
    """插件管理 API 测试类"""

    @pytest.fixture(autouse=True)
    def setup(self):
        """测试前置设置"""
        # 创建 mock 的 PluginManager
        self.mock_manager = MagicMock()
        
        # Patch get_plugin_manager 返回 mock
        self.patcher = patch(
            "neurova.api.endpoints.plugin._get_plugin_manager",
            return_value=self.mock_manager,
        )
        self.mock_get_manager = self.patcher.start()
        
        # 创建测试客户端
        from neurova.api.endpoints.plugin import router
        
        # 模拟 app.py 中的路由注册方式
        app = FastAPI()
        
        # 注册异常处理器
        @app.exception_handler(APIError)
        async def api_error_handler(request: Request, exc: APIError):
            """处理 APIError 异常"""
            return JSONResponse(
                status_code=exc.http_status,
                json={"code": exc.code, "message": exc.message, "data": exc.data},
            )
        
        api_v1 = APIRouter(prefix="/api/v1")
        api_v1.include_router(router)  # router 已有 prefix="/plugins"
        app.include_router(api_v1)
        
        self.client = TestClient(app)
        
        yield
        
        # 清理
        self.patcher.stop()

    def test_list_plugins_success(self):
        """测试获取插件列表 - 成功"""
        # Mock 数据
        mock_record = MagicMock()
        mock_record.to_dict.return_value = {
            "manifest": {
                "plugin_id": "test-plugin",
                "name": "Test Plugin",
                "version": "1.0.0",
            },
            "state": "installed",
        }
        
        self.mock_manager.list_plugins.return_value = [mock_record]
        
        # 发送请求
        response = self.client.get("/api/v1/plugins")
        
        # 验证
        assert response.status_code == 200
        data = response.json()
        # APIResponse.ok() 返回 code=0 表示成功
        assert data["code"] == 0
        assert data["data"]["count"] == 1

    def test_list_plugins_with_filter(self):
        """测试获取插件列表 - 带过滤条件"""
        self.mock_manager.list_plugins.return_value = []
        
        # 发送请求（带过滤条件，使用小写值）
        response = self.client.get(
            "/api/v1/plugins",
            params={"plugin_type": "skill", "state": "enabled"},
        )
        
        # 验证
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        self.mock_manager.list_plugins.assert_called_once()

    def test_get_plugin_success(self):
        """测试获取插件详情 - 成功"""
        mock_record = MagicMock()
        mock_record.to_dict.return_value = {
            "manifest": {
                "plugin_id": "test-plugin",
                "name": "Test Plugin",
            },
            "state": "enabled",
        }
        
        self.mock_manager.get_plugin.return_value = mock_record
        
        # 发送请求
        response = self.client.get("/api/v1/plugins/test-plugin")
        
        # 验证
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0

    def test_get_plugin_not_found(self):
        """测试获取插件详情 - 插件不存在"""
        self.mock_manager.get_plugin.return_value = None
        
        # 发送请求
        response = self.client.get("/api/v1/plugins/non-existent")
        
        # 验证（应该返回错误码）
        assert response.status_code == 200
        data = response.json()
        # 插件不存在时返回错误
        assert data["code"] != 0

    def test_enable_plugin_success(self):
        """测试启用插件 - 成功"""
        # 使用 AsyncMock 替代普通 Mock
        self.mock_manager.enable_plugin = AsyncMock(return_value=True)
        
        mock_record = MagicMock()
        mock_record.to_dict.return_value = {
            "plugin_id": "test-plugin",
            "state": "enabled",
        }
        self.mock_manager.get_plugin.return_value = mock_record
        
        # 发送请求
        response = self.client.post("/api/v1/plugins/test-plugin/enable")
        
        # 验证
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        self.mock_manager.enable_plugin.assert_called_once_with("test-plugin")

    def test_disable_plugin_success(self):
        """测试禁用插件 - 成功"""
        # 使用 AsyncMock 替代普通 Mock
        self.mock_manager.disable_plugin = AsyncMock(return_value=True)
        
        mock_record = MagicMock()
        mock_record.to_dict.return_value = {
            "plugin_id": "test-plugin",
            "state": "disabled",
        }
        self.mock_manager.get_plugin.return_value = mock_record
        
        # 发送请求
        response = self.client.post("/api/v1/plugins/test-plugin/disable")
        
        # 验证
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        self.mock_manager.disable_plugin.assert_called_once_with("test-plugin")

    def test_load_plugin_success(self):
        """测试加载插件 - 成功"""
        # 使用 AsyncMock 替代普通 Mock
        self.mock_manager.load_plugin = AsyncMock(return_value=True)
        
        mock_record = MagicMock()
        mock_record.to_dict.return_value = {
            "plugin_id": "test-plugin",
            "state": "loaded",
        }
        self.mock_manager.get_plugin.return_value = mock_record
        
        # 发送请求
        response = self.client.post("/api/v1/plugins/test-plugin/load")
        
        # 验证
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        self.mock_manager.load_plugin.assert_called_once_with("test-plugin")

    def test_unload_plugin_success(self):
        """测试卸载插件 - 成功"""
        # 使用 AsyncMock 替代普通 Mock
        self.mock_manager.unload_plugin = AsyncMock(return_value=True)
        
        mock_record = MagicMock()
        mock_record.to_dict.return_value = {
            "plugin_id": "test-plugin",
            "state": "installed",
        }
        self.mock_manager.get_plugin.return_value = mock_record
        
        # 发送请求
        response = self.client.post("/api/v1/plugins/test-plugin/unload")
        
        # 验证
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        self.mock_manager.unload_plugin.assert_called_once_with("test-plugin")

    def test_get_plugin_status(self):
        """测试获取插件管理器状态"""
        self.mock_manager.get_status.return_value = {
            "plugin_dir": "/path/to/plugins",
            "total_plugins": 5,
            "enabled_plugins": 3,
        }
        
        # 发送请求 - 使用 /plugin-status 避免与 /{plugin_id} 冲突
        response = self.client.get("/api/v1/plugins/plugin-status")
        
        # 验证
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        # 检查 data 中是否有插件状态信息
        assert "plugin_dir" in data["data"]
        assert data["data"]["total_plugins"] == 5

    def test_market_list_not_implemented(self):
        """测试插件市场列表接口 - 预留未实现"""
        # 发送请求
        response = self.client.get("/api/v1/plugins/plugin-market/list")
        
        # 验证（应该返回错误码，因为接口未实现）
        assert response.status_code == 200
        data = response.json()
        # APIError 会返回非 0 的 code
        assert data["code"] != 0
        assert "未上线" in data.get("message", "") or "Not Implemented" in data.get("message", "")

    def test_market_install_not_implemented(self):
        """测试插件市场安装接口 - 预留未实现"""
        # 发送请求
        response = self.client.post("/api/v1/plugins/plugin-market/install")
        
        # 验证
        assert response.status_code == 200
        data = response.json()
        assert data["code"] != 0
        assert "未上线" in data.get("message", "") or "Not Implemented" in data.get("message", "")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
