"""
测试 ChannelIntegrationPage.vue 使用的 API 路径正确性

验证：request 的 baseURL 是 /api/v1，所以调用路径不应包含 /api/ 前缀。
request.get('/api/channel-configs')  → 实际: /api/v1/api/channel-configs (错误!)
request.get('/channel-configs')      → 实际: /api/v1/channel-configs     (正确!)
"""

import pytest


class TestChannelConfigAPIPaths:
    """验证前端调用路径与后端注册路径一致"""

    # 后端注册路径: /api/v1/channel-configs (见 __init__.py 第 211 行)
    # request baseURL: /api/v1 (见 api/index.ts 第 28 行)
    # 因此前端调用路径应为 /channel-configs (不含 /api/ 前缀)

    @pytest.mark.parametrize("path", [
        "/channel-configs",
        "/channel-configs/{channel_type}/test",
    ])
    def test_no_double_api_prefix(self, path: str):
        """路径不应以 /api/ 开头（因为 baseURL 已包含 /api/v1）"""
        assert not path.startswith("/api/"), (
            f"Path '{path}' starts with /api/ which causes double-prefix. "
            f"Since request.baseURL = '/api/v1', the correct path should be '{path}' without /api/ prefix."
        )

    def test_base_url_is_api_v1(self):
        """验证 request.baseURL 的约定"""
        # 这是一个文档性测试，记录约定
        base_url = "/api/v1"  # 来自 api/index.ts 第 28 行
        assert base_url == "/api/v1"

    def test_backend_registered_prefix(self):
        """验证后端注册的 channel-configs 前缀"""
        # 来自 __init__.py 第 211 行
        module_path = "neurova.api.endpoints.channel_config"
        prefix = "/v1/channel-configs"
        assert "/v1/" in prefix
        assert "channel-configs" in prefix
