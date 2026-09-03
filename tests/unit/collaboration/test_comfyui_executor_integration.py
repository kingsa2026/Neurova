"""
ComfyUI 节点执行器集成测试 — TDD 切片 2 REFACTOR

验证切片 1 的 _execute_comfyui_node 能正确调用切片 2 的 ComfyUIClient：
1. 服务不可用时返回 failed
2. 服务可用时通过 HTTP 调用 ComfyUI /prompt
3. 网络异常时优雅降级

这是端到端的 tracer bullet：节点注册表 → 执行器 → HTTP 客户端 → ComfyUI
"""

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


class TestComfyUIExecutorIntegration:
    """切片 2 REFACTOR - 节点执行器与 HTTP 客户端集成"""

    @pytest.mark.asyncio
    async def test_executor_returns_failed_when_comfyui_unavailable(self):
        """服务不可用时，执行器应返回 failed"""
        from neurova.collaboration.neurflow.comfyui_client import (
            reset_comfyui_client,
        )
        from neurova.collaboration.neurflow.comfyui_nodes import _execute_comfyui_node

        reset_comfyui_client()
        with patch("neurova.core.config.get", return_value=None):
            result = await _execute_comfyui_node(
                "comfyui:KSampler",
                {"seed": 1, "steps": 20},
                {"model": "mock"},
            )

        assert result["status"] == "failed"
        assert "ComfyUI" in result["error"] or "不可用" in result["error"]

    @pytest.mark.asyncio
    async def test_executor_calls_comfyui_prompt_when_available(self):
        """服务可用时，执行器应通过 HTTP 调用 ComfyUI /prompt"""
        from neurova.collaboration.neurflow.comfyui_client import reset_comfyui_client
        from neurova.collaboration.neurflow.comfyui_nodes import _execute_comfyui_node

        reset_comfyui_client()

        def mock_get(key, default=None):
            if key == "NEUROVA_COMFYUI_HOST":
                return "http://localhost:8188"
            return default

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"prompt_id": "integ-001", "number": 1, "node_errors": {}}
        mock_response.raise_for_status = MagicMock()

        with patch("neurova.core.config.get", side_effect=mock_get), \
             patch("httpx.AsyncClient.post", new=AsyncMock(return_value=mock_response)) as mock_post:
            result = await _execute_comfyui_node(
                "comfyui:KSampler",
                {"seed": 42, "steps": 20, "cfg": 8.0},
                {"model": "model-ref"},
            )

        assert result["status"] == "success", f"应成功，实际: {result}"
        assert result["output"]["prompt_id"] == "integ-001"
        assert mock_post.called, "应调用 httpx.AsyncClient.post"

        # 验证请求体格式 — ComfyUI API 应包含 class_type 和 inputs
        call_kwargs = mock_post.call_args.kwargs
        payload = call_kwargs.get("json", {})
        assert "prompt" in payload, "请求体应包含 prompt 字段"
        node_payload = payload["prompt"].get("1", {})
        assert node_payload["class_type"] == "KSampler", "class_type 应剥离 comfyui: 前缀"
        assert "seed" in node_payload["inputs"], "inputs 应包含节点配置"

    @pytest.mark.asyncio
    async def test_executor_handles_network_error_gracefully(self):
        """网络异常时执行器应返回 failed 而非抛出"""
        import httpx

        from neurova.collaboration.neurflow.comfyui_client import reset_comfyui_client
        from neurova.collaboration.neurflow.comfyui_nodes import _execute_comfyui_node

        reset_comfyui_client()

        def mock_get(key, default=None):
            if key == "NEUROVA_COMFYUI_HOST":
                return "http://localhost:8188"
            return default

        with patch("neurova.core.config.get", side_effect=mock_get), \
             patch("httpx.AsyncClient.post", new=AsyncMock(side_effect=httpx.ConnectError("network down"))):
            result = await _execute_comfyui_node(
                "comfyui:VAEDecode",
                {},
                {"samples": "latent-ref", "vae": "vae-ref"},
            )

        assert result["status"] == "failed"
        assert "error" in result

    @pytest.mark.asyncio
    async def test_executor_strips_comfyui_prefix_from_class_type(self):
        """执行器应正确剥离 comfyui: 前缀"""
        from neurova.collaboration.neurflow.comfyui_client import reset_comfyui_client
        from neurova.collaboration.neurflow.comfyui_nodes import _execute_comfyui_node

        reset_comfyui_client()

        def mock_get(key, default=None):
            if key == "NEUROVA_COMFYUI_HOST":
                return "http://localhost:8188"
            return default

        captured_payload = {}

        def capture_post(url, json=None, **kwargs):
            captured_payload["url"] = url
            captured_payload["json"] = json
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"prompt_id": "prefix-test"}
            mock_resp.raise_for_status = MagicMock()
            return mock_resp

        with patch("neurova.core.config.get", side_effect=mock_get), \
             patch("httpx.AsyncClient.post", new=AsyncMock(side_effect=capture_post)):
            await _execute_comfyui_node(
                "comfyui:CheckpointLoaderSimple",
                {"ckpt_name": "model.safetensors"},
                {},
            )

        # 验证 class_type 已剥离 comfyui: 前缀
        node_payload = captured_payload["json"]["prompt"]["1"]
        assert node_payload["class_type"] == "CheckpointLoaderSimple", \
            f"class_type 应为 CheckpointLoaderSimple（无前缀），实际: {node_payload['class_type']}"
