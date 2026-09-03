"""
ComfyUI HTTP 客户端测试 — TDD 切片 2

验证 ComfyUIClient 能：
1. 以单例模式获取（get_comfyui_client）
2. 检测服务可用性（is_available）
3. 通过 HTTP 调用 ComfyUI /prompt 端点执行节点（execute_node）
4. 处理服务不可用 / 网络异常等失败场景

RED: 测试应先失败（comfyui_client 模块不存在）
"""

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


class TestComfyUIClientSingleton:
    """切片 2 - 单例模式"""

    def test_get_comfyui_client_returns_singleton_instance(self):
        """RED: get_comfyui_client 应返回单例"""
        from neurova.collaboration.neurflow.comfyui_client import (
            get_comfyui_client,
            reset_comfyui_client,
        )

        reset_comfyui_client()
        client1 = get_comfyui_client()
        client2 = get_comfyui_client()

        assert client1 is client2, "get_comfyui_client 应返回同一单例实例"

    def test_reset_comfyui_client_creates_new_instance(self):
        """RED: reset_comfyui_client 后应获取新实例"""
        from neurova.collaboration.neurflow.comfyui_client import (
            get_comfyui_client,
            reset_comfyui_client,
        )

        reset_comfyui_client()
        client1 = get_comfyui_client()
        reset_comfyui_client()
        client2 = get_comfyui_client()

        assert client1 is not client2, "重置后应得到新实例"


class TestComfyUIClientAvailability:
    """切片 2 - 服务可用性检测"""

    def test_is_available_returns_false_when_not_configured(self):
        """RED: 未配置 NEUROVA_COMFYUI_HOST 时 is_available 应返回 False"""
        from neurova.collaboration.neurflow.comfyui_client import (
            get_comfyui_client,
            reset_comfyui_client,
        )

        reset_comfyui_client()
        with patch("neurova.core.config.get", return_value=None):
            client = get_comfyui_client()
            assert client.is_available() is False, "未配置时应返回 False"

    def test_is_available_returns_true_when_host_configured(self):
        """RED: 配置 NEUROVA_COMFYUI_HOST 后 is_available 应返回 True"""
        from neurova.collaboration.neurflow.comfyui_client import (
            get_comfyui_client,
            reset_comfyui_client,
        )

        reset_comfyui_client()

        def mock_get(key, default=None):
            if key == "NEUROVA_COMFYUI_HOST":
                return "http://localhost:8188"
            return default

        with patch("neurova.core.config.get", side_effect=mock_get):
            client = get_comfyui_client()
            assert client.is_available() is True, "配置 host 后应返回 True"


class TestComfyUIClientExecuteNode:
    """切片 2 - 节点执行（HTTP 调用 ComfyUI /prompt）"""

    @pytest.mark.asyncio
    async def test_execute_node_returns_failed_when_unavailable(self):
        """RED: 服务不可用时 execute_node 应返回 failed 状态"""
        from neurova.collaboration.neurflow.comfyui_client import (
            get_comfyui_client,
            reset_comfyui_client,
        )

        reset_comfyui_client()
        with patch("neurova.core.config.get", return_value=None):
            client = get_comfyui_client()
            result = await client.execute_node(
                "KSampler",
                {"seed": 1, "steps": 20},
                {"model": "mock-model"},
            )

        assert result["status"] == "failed", "不可用时应返回 failed"
        assert "error" in result, "应包含 error 字段"
        assert result["output"] is None, "不可用时 output 应为 None"

    @pytest.mark.asyncio
    async def test_execute_node_calls_comfyui_prompt_endpoint(self):
        """RED: 可用时 execute_node 应通过 httpx 调用 ComfyUI /prompt 端点"""
        from neurova.collaboration.neurflow.comfyui_client import (
            get_comfyui_client,
            reset_comfyui_client,
        )

        reset_comfyui_client()

        def mock_get(key, default=None):
            if key == "NEUROVA_COMFYUI_HOST":
                return "http://localhost:8188"
            return default

        # mock httpx.AsyncClient.post
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "prompt_id": "test-prompt-001",
            "number": 1,
            "node_errors": {},
        }
        mock_response.raise_for_status = MagicMock()

        with patch("neurova.core.config.get", side_effect=mock_get), \
             patch("httpx.AsyncClient.post", new=AsyncMock(return_value=mock_response)) as mock_post:
            client = get_comfyui_client()
            result = await client.execute_node(
                "KSampler",
                {"seed": 1, "steps": 20, "cfg": 8.0},
                {"model": "mock-model-ref"},
            )

        # 应调用 POST /prompt
        assert mock_post.called, "应调用 httpx.AsyncClient.post"
        call_args = mock_post.call_args
        url = call_args.args[0] if call_args.args else call_args.kwargs.get("url", "")
        assert "/prompt" in str(url), f"应调用 /prompt 端点，实际 URL: {url}"

        # 应返回成功结果
        assert result["status"] == "success", f"应返回 success，实际: {result}"
        assert "prompt_id" in result["output"], "output 应包含 prompt_id"

    @pytest.mark.asyncio
    async def test_execute_node_handles_network_error(self):
        """RED: 网络异常时应返回 failed 而非抛出"""
        from neurova.collaboration.neurflow.comfyui_client import (
            get_comfyui_client,
            reset_comfyui_client,
        )

        reset_comfyui_client()

        def mock_get(key, default=None):
            if key == "NEUROVA_COMFYUI_HOST":
                return "http://localhost:8188"
            return default

        import httpx
        with patch("neurova.core.config.get", side_effect=mock_get), \
             patch("httpx.AsyncClient.post", new=AsyncMock(side_effect=httpx.ConnectError("connection refused"))):
            client = get_comfyui_client()
            result = await client.execute_node(
                "KSampler",
                {"seed": 1},
                {"model": "mock"},
            )

        assert result["status"] == "failed", "网络异常时应返回 failed"
        assert "error" in result, "应包含错误信息"
        assert "connection" in result["error"].lower() or "refused" in result["error"].lower(), \
            f"错误信息应反映连接问题，实际: {result['error']}"

    @pytest.mark.asyncio
    async def test_execute_node_handles_http_error_response(self):
        """RED: ComfyUI 返回 4xx/5xx 时应返回 failed"""
        from neurova.collaboration.neurflow.comfyui_client import (
            get_comfyui_client,
            reset_comfyui_client,
        )

        reset_comfyui_client()

        def mock_get(key, default=None):
            if key == "NEUROVA_COMFYUI_HOST":
                return "http://localhost:8188"
            return default

        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Invalid node configuration"
        mock_response.raise_for_status = MagicMock(side_effect=Exception("HTTP 400"))

        with patch("neurova.core.config.get", side_effect=mock_get), \
             patch("httpx.AsyncClient.post", new=AsyncMock(return_value=mock_response)):
            client = get_comfyui_client()
            result = await client.execute_node(
                "KSampler",
                {"seed": 1},
                {"model": "mock"},
            )

        assert result["status"] == "failed", "HTTP 错误时应返回 failed"
        assert "error" in result, "应包含错误信息"


class TestComfyUIClientConfigResolution:
    """切片 2 - 配置解析"""

    def test_client_reads_host_from_env(self):
        """RED: 客户端应从 NEUROVA_COMFYUI_HOST 读取主机地址"""
        from neurova.collaboration.neurflow.comfyui_client import (
            get_comfyui_client,
            reset_comfyui_client,
        )

        reset_comfyui_client()

        def mock_get(key, default=None):
            if key == "NEUROVA_COMFYUI_HOST":
                return "http://192.168.1.100:8188"
            return default

        with patch("neurova.core.config.get", side_effect=mock_get):
            client = get_comfyui_client()
            assert client.host == "http://192.168.1.100:8188", \
                f"应读取 NEUROVA_COMFYUI_HOST，实际: {client.host}"

    def test_client_default_host_is_none(self):
        """RED: 未配置时 host 应为 None"""
        from neurova.collaboration.neurflow.comfyui_client import (
            get_comfyui_client,
            reset_comfyui_client,
        )

        reset_comfyui_client()
        with patch("neurova.core.config.get", return_value=None):
            client = get_comfyui_client()
            assert client.host is None, "未配置时 host 应为 None"
