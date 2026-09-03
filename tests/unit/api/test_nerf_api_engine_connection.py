"""
测试 NeRF API 端点与 RecallEngine 的连接

验证：
1. API 设置更新能同步到引擎
2. 引擎设置能反映到 API 响应
3. 多 Agent 场景下的同步
4. 重置功能正常工作
"""

import pytest
from unittest.mock import MagicMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient


# 模拟 NeurovaRecallEngine
class MockRecallEngine:
    def __init__(self, fusion_mode="legacy", density_scale=1.0):
        self.fusion_mode = fusion_mode
        self.density_scale = density_scale
        self.channel_densities = {
            "temperature": 0.7,
            "text": 0.9,
            "category": 0.5,
            "graph": 0.6,
            "emotion": 0.8,
            "voice": 0.4,
        }
        self._update_calls = []

    def get_fusion_settings(self):
        return {
            "fusion_mode": self.fusion_mode,
            "density_scale": self.density_scale,
            "channel_densities": self.channel_densities.copy(),
        }

    def update_fusion_settings(self, fusion_mode=None, density_scale=None, channel_densities=None):
        self._update_calls.append({
            "fusion_mode": fusion_mode,
            "density_scale": density_scale,
            "channel_densities": channel_densities,
        })
        if fusion_mode is not None:
            self.fusion_mode = fusion_mode
        if density_scale is not None:
            self.density_scale = density_scale
        if channel_densities:
            self.channel_densities.update(channel_densities)


# 模拟 Agent
class MockAgent:
    def __init__(self, recall_engine):
        self.memory_agent = MagicMock()
        self.memory_agent.recall_engine = recall_engine


@pytest.fixture
def mock_app():
    """创建带有模拟 Agent 的 FastAPI 应用"""
    app = FastAPI()
    app.state.agents = {}
    return app


@pytest.fixture
def mock_engine():
    """创建模拟的 RecallEngine"""
    return MockRecallEngine()


@pytest.fixture
def client(mock_app):
    """创建测试客户端（mock 认证为 admin — nerf-settings 写端点仅管理员）"""
    # 导入并注册路由
    from neurova.api.endpoints.enhanced_memory_search_api import router
    from neurova.api.deps import get_current_user
    mock_app.include_router(router, prefix="/v1/enhanced-memory-search")
    mock_app.dependency_overrides[get_current_user] = lambda: {
        "user_id": "admin_user", "username": "adminuser", "role": "admin",
    }
    return TestClient(mock_app)


class TestGetNerfSettings:
    """测试 GET /nerf-settings 端点"""

    def test_get_settings_no_agents(self, client):
        """没有活跃 Agent 时返回默认设置"""
        response = client.get("/v1/enhanced-memory-search/nerf-settings")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert data["data"]["fusion_mode"] == "legacy"
        assert data["data"]["density_scale"] == 1.0
        assert data["data"]["active_engines_count"] == 0

    def test_get_settings_with_agent(self, client, mock_app, mock_engine):
        """有活跃 Agent 时返回引擎设置"""
        # 注册模拟 Agent
        mock_app.state.agents["agent_1"] = MockAgent(mock_engine)

        response = client.get("/v1/enhanced-memory-search/nerf-settings")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert data["data"]["fusion_mode"] == "legacy"
        assert data["data"]["active_engines_count"] == 1

    def test_get_settings_reflects_engine_changes(self, client, mock_app, mock_engine):
        """设置能反映引擎的实时变化"""
        mock_app.state.agents["agent_1"] = MockAgent(mock_engine)

        # 修改引擎设置
        mock_engine.fusion_mode = "nerf"
        mock_engine.density_scale = 2.0

        response = client.get("/v1/enhanced-memory-search/nerf-settings")
        data = response.json()
        assert data["data"]["fusion_mode"] == "nerf"
        assert data["data"]["density_scale"] == 2.0


class TestUpdateNerfSettings:
    """测试 PUT /nerf-settings 端点"""

    def test_update_fusion_mode(self, client, mock_app, mock_engine):
        """更新 fusion_mode 并同步到引擎"""
        mock_app.state.agents["agent_1"] = MockAgent(mock_engine)

        response = client.put(
            "/v1/enhanced-memory-search/nerf-settings",
            json={"fusion_mode": "nerf"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert data["data"]["fusion_mode"] == "nerf"
        assert data["data"]["engines_updated"] == 1

        # 验证引擎已更新
        assert mock_engine.fusion_mode == "nerf"
        assert len(mock_engine._update_calls) == 1
        assert mock_engine._update_calls[0]["fusion_mode"] == "nerf"

    def test_update_density_scale(self, client, mock_app, mock_engine):
        """更新 density_scale 并同步到引擎"""
        mock_app.state.agents["agent_1"] = MockAgent(mock_engine)

        response = client.put(
            "/v1/enhanced-memory-search/nerf-settings",
            json={"density_scale": 2.5}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["data"]["density_scale"] == 2.5

        # 验证引擎已更新
        assert mock_engine.density_scale == 2.5

    def test_update_channel_densities(self, client, mock_app, mock_engine):
        """更新 channel_densities 并同步到引擎"""
        mock_app.state.agents["agent_1"] = MockAgent(mock_engine)

        response = client.put(
            "/v1/enhanced-memory-search/nerf-settings",
            json={"channel_densities": {"text": 0.95, "emotion": 0.85}}
        )
        assert response.status_code == 200

        # 验证引擎已更新
        assert mock_engine.channel_densities["text"] == 0.95
        assert mock_engine.channel_densities["emotion"] == 0.85
        # 其他通道保持不变
        assert mock_engine.channel_densities["temperature"] == 0.7

    def test_update_invalid_fusion_mode(self, client):
        """无效的 fusion_mode 应返回 400"""
        response = client.put(
            "/v1/enhanced-memory-search/nerf-settings",
            json={"fusion_mode": "invalid_mode"}
        )
        assert response.status_code == 400

    def test_update_density_scale_clamping(self, client, mock_app, mock_engine):
        """density_scale 应被限制在 [0.1, 5.0] 范围内"""
        mock_app.state.agents["agent_1"] = MockAgent(mock_engine)

        # 测试下限
        response = client.put(
            "/v1/enhanced-memory-search/nerf-settings",
            json={"density_scale": 0.01}
        )
        assert response.status_code == 200
        assert mock_engine.density_scale == 0.1

        # 测试上限
        response = client.put(
            "/v1/enhanced-memory-search/nerf-settings",
            json={"density_scale": 10.0}
        )
        assert response.status_code == 200
        assert mock_engine.density_scale == 5.0

    def test_update_multiple_agents(self, client, mock_app):
        """多个 Agent 的设置应同步更新"""
        engine1 = MockRecallEngine()
        engine2 = MockRecallEngine()
        mock_app.state.agents["agent_1"] = MockAgent(engine1)
        mock_app.state.agents["agent_2"] = MockAgent(engine2)

        response = client.put(
            "/v1/enhanced-memory-search/nerf-settings",
            json={"fusion_mode": "nerf", "density_scale": 1.5}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["data"]["engines_updated"] == 2

        # 验证两个引擎都已更新
        assert engine1.fusion_mode == "nerf"
        assert engine2.fusion_mode == "nerf"
        assert engine1.density_scale == 1.5
        assert engine2.density_scale == 1.5


class TestResetNerfSettings:
    """测试 POST /nerf-settings/reset 端点"""

    def test_reset_settings(self, client, mock_app, mock_engine):
        """重置设置应恢复默认值"""
        mock_app.state.agents["agent_1"] = MockAgent(mock_engine)

        # 先修改设置
        mock_engine.fusion_mode = "nerf"
        mock_engine.density_scale = 3.0
        mock_engine.channel_densities["text"] = 0.99

        # 重置
        response = client.post("/v1/enhanced-memory-search/nerf-settings/reset")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert data["data"]["fusion_mode"] == "legacy"
        assert data["data"]["density_scale"] == 1.0
        assert data["data"]["engines_updated"] == 1

        # 验证引擎已重置
        assert mock_engine.fusion_mode == "legacy"
        assert mock_engine.density_scale == 1.0
        assert mock_engine.channel_densities["text"] == 0.9

    def test_reset_multiple_agents(self, client, mock_app):
        """重置应同步到所有 Agent"""
        engine1 = MockRecallEngine(fusion_mode="nerf", density_scale=2.0)
        engine2 = MockRecallEngine(fusion_mode="nerf", density_scale=3.0)
        mock_app.state.agents["agent_1"] = MockAgent(engine1)
        mock_app.state.agents["agent_2"] = MockAgent(engine2)

        response = client.post("/v1/enhanced-memory-search/nerf-settings/reset")
        assert response.status_code == 200
        data = response.json()
        assert data["data"]["engines_updated"] == 2

        # 验证两个引擎都已重置
        assert engine1.fusion_mode == "legacy"
        assert engine2.fusion_mode == "legacy"
        assert engine1.density_scale == 1.0
        assert engine2.density_scale == 1.0


class TestEdgeCases:
    """测试边界情况"""

    def test_agent_without_memory_agent(self, client, mock_app):
        """Agent 没有 memory_agent 属性时不应崩溃"""
        agent = MagicMock(spec=[])  # 没有任何属性
        mock_app.state.agents["agent_1"] = agent

        response = client.get("/v1/enhanced-memory-search/nerf-settings")
        assert response.status_code == 200
        assert response.json()["data"]["active_engines_count"] == 0

    def test_agent_without_recall_engine(self, client, mock_app):
        """Agent 的 memory_agent 没有 recall_engine 时不应崩溃"""
        agent = MagicMock()
        agent.memory_agent = MagicMock(spec=[])  # 没有 recall_engine
        mock_app.state.agents["agent_1"] = agent

        response = client.get("/v1/enhanced-memory-search/nerf-settings")
        assert response.status_code == 200
        assert response.json()["data"]["active_engines_count"] == 0

    def test_engine_update_failure_continues(self, client, mock_app):
        """一个引擎更新失败时，其他引擎应继续更新"""
        engine1 = MockRecallEngine()
        engine2 = MockRecallEngine()

        # 让 engine1 的 update_fusion_settings 抛出异常
        def failing_update(**kwargs):
            raise RuntimeError("Engine update failed")

        engine1.update_fusion_settings = failing_update

        mock_app.state.agents["agent_1"] = MockAgent(engine1)
        mock_app.state.agents["agent_2"] = MockAgent(engine2)

        response = client.put(
            "/v1/enhanced-memory-search/nerf-settings",
            json={"fusion_mode": "nerf"}
        )
        assert response.status_code == 200
        data = response.json()
        # 只有 engine2 更新成功
        assert data["data"]["engines_updated"] == 1


class TestApiEndpointFormats:
    """测试 API 响应格式"""

    def test_get_settings_response_format(self, client):
        """验证 GET /nerf-settings 响应格式"""
        response = client.get("/v1/enhanced-memory-search/nerf-settings")
        data = response.json()

        assert "code" in data
        assert "message" in data
        assert "data" in data

        settings = data["data"]
        assert "fusion_mode" in settings
        assert "density_scale" in settings
        assert "channel_densities" in settings
        assert "available_modes" in settings
        assert "mode_descriptions" in settings
        assert "active_engines_count" in settings

        assert settings["available_modes"] == ["legacy", "nerf"]
        assert "legacy" in settings["mode_descriptions"]
        assert "nerf" in settings["mode_descriptions"]

    def test_update_settings_response_format(self, client):
        """验证 PUT /nerf-settings 响应格式"""
        response = client.put(
            "/v1/enhanced-memory-search/nerf-settings",
            json={"fusion_mode": "nerf"}
        )
        data = response.json()

        assert "code" in data
        assert "message" in data
        assert "data" in data

        settings = data["data"]
        assert "fusion_mode" in settings
        assert "density_scale" in settings
        assert "channel_densities" in settings
        assert "engines_updated" in settings

    def test_reset_settings_response_format(self, client):
        """验证 POST /nerf-settings/reset 响应格式"""
        response = client.post("/v1/enhanced-memory-search/nerf-settings/reset")
        data = response.json()

        assert "code" in data
        assert "message" in data
        assert "data" in data

        settings = data["data"]
        assert "fusion_mode" in settings
        assert "density_scale" in settings
        assert "channel_densities" in settings
        assert "engines_updated" in settings


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
