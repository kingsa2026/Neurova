"""
CORS 白名单桌面壳来源防回归测试

背景（2026-09-02 桌面版注册/登录全挂事故）:
    Tauri v2 桌面壳 WebView 的 origin 是 http://tauri.localhost（Windows），
    前端从该 origin 调 http://127.0.0.1:9527 属跨域，所有请求先过 CORS 预检。
    三级优先级（env → config/cors.json → 代码默认值）必须至少一层放行该 origin。

    事故链: config/cors.json 被污染为仅含 https://evil.example.com 并随 dee84dc
    入库 → 打包脚本原样带进安装包 → 旧壳（未注入 NEUROVA_CORS_ORIGINS）落到
    配置文件级 → 预检 400 Disallowed CORS origin → 注册/登录全部 Network Error。

契约:
    1. 仓库 config/cors.json 必须包含开发端口与 tauri.localhost（防再次污染入库）
    2. middleware 兜底默认值（配置文件缺失时）必须包含 tauri.localhost
    3. settings API 的默认 origins 必须包含 tauri.localhost
    4. 端到端预检: OPTIONS + Origin: http://tauri.localhost → 200 + ACAO 回显
    5. 非白名单 origin 的预检仍被拒绝（安全语义不回退）
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api import middleware as cors_middleware
from neurova.api.endpoints import settings as settings_module

REPO_ROOT = Path(__file__).resolve().parents[3]
REPO_CORS_CONFIG = REPO_ROOT / "config" / "cors.json"

TAURI_ORIGINS = {"http://tauri.localhost", "https://tauri.localhost"}


@pytest.fixture
def no_cors_env(monkeypatch):
    """屏蔽环境变量干扰，强制走到配置文件/默认值分支。"""
    monkeypatch.setattr(
        "neurova.core.config.get", lambda key, default="": default if key == "NEUROVA_CORS_ORIGINS" else default
    )


def test_repo_cors_config_includes_tauri_origins():
    """仓库 cors.json 是打包产物的直接来源，必须自带桌面壳 origin（防污染再入库）。"""
    data = json.loads(REPO_CORS_CONFIG.read_text(encoding="utf-8"))
    origins = set(data.get("origins", []))
    assert TAURI_ORIGINS <= origins, f"cors.json 缺少桌面壳 origin: {TAURI_ORIGINS - origins}"
    assert "http://localhost:8100" in origins, "开发端口 8100 不应被移除"
    assert "https://evil.example.com" not in origins, "测试污染 origin 不得出现在仓库配置"


def test_middleware_defaults_include_tauri_origins():
    """配置文件缺失时的兜底默认值也必须放行桌面壳 origin。"""
    defaults = set(getattr(cors_middleware, "DEFAULT_CORS_ORIGINS", []))
    assert TAURI_ORIGINS <= defaults, f"middleware 默认值缺少桌面壳 origin: {TAURI_ORIGINS - defaults}"


def test_load_origins_falls_back_to_defaults_without_config(tmp_path, no_cors_env):
    """env 未设置且配置文件不存在 → 返回含 tauri origin 的默认值。"""
    origins = cors_middleware._load_cors_origins_from_config(
        config_file=tmp_path / "absent" / "cors.json"
    )
    assert TAURI_ORIGINS <= set(origins)


def test_settings_default_origins_include_tauri():
    """settings API 的默认 origins（文件缺失/管理端展示）必须包含桌面壳 origin。"""
    defaults = set(settings_module._DEFAULT_CORS_ORIGINS)
    assert TAURI_ORIGINS <= defaults, f"settings 默认值缺少桌面壳 origin: {TAURI_ORIGINS - defaults}"


def _preflight(client: TestClient, origin: str):
    return client.options(
        "/api/v1/auth/register",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )


@pytest.fixture
def middleware_app(no_cors_env):
    """挂载真实 CORS 中间件链的最小应用（读仓库 cors.json，端到端复刻桌面壳请求）。"""
    app = FastAPI()
    cors_middleware.setup_middleware(app)

    @app.post("/api/v1/auth/register")
    async def _register():  # pragma: no cover - 预检不会到达路由
        return {"ok": True}

    return TestClient(app)


def test_preflight_from_tauri_origin_allowed(middleware_app):
    """桌面壳真实预检场景：tauri.localhost 必须放行且回显 ACAO。"""
    resp = _preflight(middleware_app, "http://tauri.localhost")
    assert resp.status_code == 200, resp.text
    assert resp.headers.get("access-control-allow-origin") == "http://tauri.localhost"


def test_preflight_from_unknown_origin_rejected(middleware_app):
    """安全语义不回退：非白名单 origin 的预检必须被拒绝。"""
    resp = _preflight(middleware_app, "https://evil.example.com")
    assert resp.status_code == 400
