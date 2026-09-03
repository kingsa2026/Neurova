"""
ComfyUI API 端点测试 — TDD 切片 4

验证 Neurflow API 中的 ComfyUI 端点：
1. GET /v1/neurflow/comfyui/status — 检查 ComfyUI 服务可用性
2. POST /v1/neurflow/comfyui/execute — 直接执行单个 ComfyUI 节点

注：POST /v1/neurflow/comfyui/import 已下线——工作流 = 无限画布工作流，
导入统一走 POST /v1/collaboration/comfyui/import-canvas 落为可编辑画布
（见 tests/unit/api/test_collaboration_canvas.py 与 test_workflow_canvas_integration.py）。

使用 FastAPI TestClient + 最小 app（仅挂载 neurflow router）避免完整应用初始化。

RED: 测试应先失败（端点函数不存在）
"""

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


# ==================== 测试数据 ====================

SAMPLE_COMFYUI_WORKFLOW = {
    "1": {
        "class_type": "CheckpointLoaderSimple",
        "inputs": {"ckpt_name": "sd_xl_base_1.0.safetensors"},
    },
    "2": {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": "a beautiful landscape", "clip": ["1", 1]},
    },
}


@pytest.fixture
def app():
    """创建仅挂载 neurflow router 的最小 app"""
    from neurova.api.endpoints.neurflow_api import router
    app = FastAPI()
    app.include_router(router, prefix="/v1/neurflow")
    return app


@pytest.fixture
def client(app):
    """TestClient fixture"""
    return TestClient(app)


class TestComfyUIStatusEndpoint:
    """切片 4 - GET /v1/neurflow/comfyui/status"""

    def test_status_returns_false_when_not_configured(self, client):
        """RED: 未配置时 status 应返回 available=false"""
        with patch("neurova.core.config.get", return_value=None):
            response = client.get("/v1/neurflow/comfyui/status")

        assert response.status_code == 200
        data = response.json()
        assert data["available"] is False
        assert "host" in data

    def test_status_returns_true_when_configured(self, client):
        """RED: 配置 host 后 status 应返回 available=true"""
        from neurova.collaboration.neurflow.comfyui_client import reset_comfyui_client

        reset_comfyui_client()

        def mock_get(key, default=None):
            if key == "NEUROVA_COMFYUI_HOST":
                return "http://localhost:8188"
            return default

        with patch("neurova.core.config.get", side_effect=mock_get):
            response = client.get("/v1/neurflow/comfyui/status")

        assert response.status_code == 200
        data = response.json()
        assert data["available"] is True
        assert data["host"] == "http://localhost:8188"


class TestComfyUIExecuteEndpoint:
    """切片 4 - POST /v1/neurflow/comfyui/execute"""

    def test_execute_node_returns_failed_when_unavailable(self, client):
        """RED: 服务不可用时 execute 应返回 failed"""
        from neurova.collaboration.neurflow.comfyui_client import reset_comfyui_client

        reset_comfyui_client()

        with patch("neurova.core.config.get", return_value=None):
            response = client.post(
                "/v1/neurflow/comfyui/execute",
                json={
                    "class_type": "KSampler",
                    "config": {"seed": 1, "steps": 20},
                    "inputs": {"model": "mock"},
                },
            )

        assert response.status_code == 200, f"应返回 200，实际: {response.status_code}"
        data = response.json()
        assert data["status"] == "failed"
        assert "error" in data

    def test_execute_node_calls_comfyui_when_available(self, client):
        """RED: 服务可用时 execute 应调用 ComfyUI /prompt"""
        from neurova.collaboration.neurflow.comfyui_client import reset_comfyui_client

        reset_comfyui_client()

        def mock_get(key, default=None):
            if key == "NEUROVA_COMFYUI_HOST":
                return "http://localhost:8188"
            return default

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"prompt_id": "api-test-001", "number": 1, "node_errors": {}}
        mock_response.raise_for_status = MagicMock()

        with patch("neurova.core.config.get", side_effect=mock_get), \
             patch("httpx.AsyncClient.post", new=AsyncMock(return_value=mock_response)):
            response = client.post(
                "/v1/neurflow/comfyui/execute",
                json={
                    "class_type": "KSampler",
                    "config": {"seed": 42, "steps": 20, "cfg": 7.5},
                    "inputs": {"model": "model-ref"},
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success", f"应成功，实际: {data}"
        assert data["output"]["prompt_id"] == "api-test-001"

    def test_execute_missing_class_type_returns_422(self, client):
        """RED: 缺少 class_type 应返回 422"""
        response = client.post(
            "/v1/neurflow/comfyui/execute",
            json={"config": {}, "inputs": {}},
        )

        assert response.status_code == 422
