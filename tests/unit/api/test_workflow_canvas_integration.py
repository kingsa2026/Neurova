"""
画布 ↔ 工作流整合（清理阶段）测试 — TDD 红灯

背景：工作流 = 无限画布工作流。画布快照是用户数据的唯一可编辑形态，
Neurflow WorkflowDefinition 只是执行时的内部编译产物。

本文件锁定四条整合契约：
1. mock 的 /v1/workflows API（纯内存存储、假执行）已彻底删除
2. 旧的 /neurflow/comfyui/import「定义优先」导入路径已下线
   （统一走 /collaboration/comfyui/import-canvas 落为可编辑画布）
3. canvas_store 的受理式 create_run 死代码已移除（已被 neurflow 执行路径取代）
4. canvas_bridge 的 Tuple 类型标注依赖完整（typing 导入不缺失）
"""

import importlib
import inspect
import sys
from typing import Tuple

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ─── 契约 1: mock /v1/workflows API 彻底删除 ───


class TestMockWorkflowsApiRemoved:
    def test_module_removed(self):
        """workflows_api.py 模块应已删除（内存假执行的死代码）"""
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module("neurova.api.endpoints.workflows_api")

    def test_route_unregistered(self):
        """端点注册表不应再注册 workflows_api"""
        endpoints_pkg = sys.modules["neurova.api.endpoints"]
        src = inspect.getsource(endpoints_pkg)
        assert "workflows_api" not in src, (
            "endpoints/__init__.py 仍注册 workflows_api；"
            "mock API 已被 neurflow + canvas 取代，应从注册表中移除"
        )


# ─── 契约 2: 旧 ComfyUI 导入路径下线（保留画布路径） ───


class TestOldComfyuiImportRetired:
    @pytest.fixture
    def client(self):
        from neurova.api.endpoints.neurflow_api import router

        app = FastAPI()
        app.include_router(router, prefix="/v1/neurflow")
        return TestClient(app)

    def test_definition_import_endpoint_retired(self, client):
        """/neurflow/comfyui/import 应返回 404——导入统一落为画布"""
        response = client.post(
            "/v1/neurflow/comfyui/import",
            json={"name": "测试", "workflow": {"1": {"class_type": "X", "inputs": {}}}},
        )
        assert response.status_code == 404, (
            f"旧导入端点应已下线(404)，实际: {response.status_code}"
        )

    def test_status_and_execute_endpoints_kept(self, client):
        """ComfyUI status/execute 与导入无关，必须保留"""
        response = client.get("/v1/neurflow/comfyui/status")
        assert response.status_code == 200


# ─── 契约 3: canvas_store.create_run 死代码移除 ───


class TestCanvasStoreRunDeadCodeRemoved:
    def test_create_run_removed(self):
        from neurova.collaboration.canvas_store import CanvasStore

        assert not hasattr(CanvasStore, "create_run"), (
            "create_run 已被 neurflow 执行路径取代（见 collaboration_api.run_canvas_workflow），"
            "属死代码，应删除"
        )

    def test_run_dir_not_created(self, tmp_path):
        """不再初始化 runs 目录——运行记录由 neurflow SQLite 管理"""
        from neurova.collaboration.canvas_store import CanvasStore

        CanvasStore(base_dir=tmp_path)
        assert not (tmp_path / "runs").exists()


# ─── 契约 4: canvas_bridge 类型标注依赖完整 ───


class TestCanvasBridgeTyping:
    def test_tuple_imported(self):
        """canvas_bridge.py 使用了 Tuple 标注，typing 导入不应缺失"""
        from neurova.collaboration import canvas_bridge

        assert getattr(canvas_bridge, "Tuple", None) is Tuple, (
            "canvas_bridge 使用 Tuple 却未从 typing 导入"
            "（当前靠 __future__ annotations 掩盖），应补全导入"
        )
