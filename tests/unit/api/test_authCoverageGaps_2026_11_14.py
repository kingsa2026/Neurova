# -*- coding: utf-8 -*-
"""鉴权收口批守卫（2026-11-14，审计 P1-1..P1-6 / P2-1..P2-6 / P3-7）。

GlobalAuthMiddleware 默认 off，端点级依赖是唯一防线。本文件把审计点名的
漏挂端点钉成机器判据：

- 匿名（无任何凭证）打本批端点 → 401/403（角色门内侧的登录门先拦，故
  admin 收口点对匿名同样是 401）；
- 普通用户（role=user）打 admin 收口点 → 403；
- 管理员打 admin 收口点 → 非 401/403（门已过、进入业务处理）；
- P2-6：`/v1/enhanced-memory-search/decay` 不再恒回 affected_count:0 的
  假成功——登录后也是诚实 501；
- P2-3：`/v1/computers/{id}/heartbeat` 是 daemon 上报面，须携带配对共享
  令牌——匿名/登录但无令牌/错令牌一律 401，对令牌 200。

app 构建方式与 `test_knowledge_conflicts_llm_advice_api.py` 同款：裸 FastAPI
挂目标 router（生产前缀取自 `ENDPOINT_MODULES` 挂载注册表），匿名矩阵不打
任何依赖覆盖（真依赖真 401）；角色矩阵用 `dependency_overrides` 换身份。
"""

import hashlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api import auth as neurova_auth
from neurova.api import deps as neurova_deps

ALICE = {"user_id": "1", "username": "alice", "role": "user", "neuser_id": "1"}
ADMIN = {"user_id": "9", "username": "admin", "role": "admin", "neuser_id": "9"}

# 本批涉及的 router 与生产挂载前缀（同 neurova/api/endpoints/__init__.py 的
# ENDPOINT_MODULES；coordination_api 前缀由模块自述 APIRouter(prefix=...) 提供）。
_TARGET_ROUTERS = [
    ("neurova.api.endpoints.enhanced_memory_search_api", "/v1/enhanced-memory-search"),
    ("neurova.api.endpoints.context", "/v1/context"),
    ("neurova.api.endpoints.agent", "/v1/agents"),
    ("neurova.api.endpoints.neurflow_api", "/v1/neurflow"),
    ("neurova.api.endpoints.collaboration_api", "/v1/collaboration"),
    ("neurova.api.endpoints.coordination_api", ""),
    ("neurova.api.endpoints.audio", "/v1/audio"),
    ("neurova.api.endpoints.stats", "/v1/stats"),
    ("neurova.api.endpoints.computer_api", "/v1"),
    ("neurova.api.endpoints.session_sync", "/v1/sync"),
    ("neurova.api.endpoints.channels", "/v1/channel-adapters"),
    ("neurova.api.endpoints.model", "/v1/models"),
    ("neurova.api.endpoints.health", "/v1/health"),
    ("neurova.api.endpoints.semantic_search_api", "/v1/semantic-search"),
    ("neurova.api.endpoints.knowledge_access_facade", "/v1/knowledge"),
]

# 匿名探针：(method, path, kwargs)。覆盖每个文件至少一个代表端点，
# 并包含全部 admin 收口点（匿名过不了登录门 → 401）。
_ANON_PROBES = [
    # P1-1 enhanced_memory_search_api（router 级）
    ("post", "/v1/enhanced-memory-search/search", {"json": {"query": "hello"}}),
    ("get", "/v1/enhanced-memory-search/stats", {}),
    ("post", "/v1/enhanced-memory-search/decay", {}),
    # P1-2 context.py 六端点
    ("get", "/v1/context/stats", {}),
    ("get", "/v1/context/ctx-1/preview", {}),
    ("post", "/v1/context/ctx-1/compress", {}),
    ("get", "/v1/context/inject/reflection", {}),
    ("get", "/v1/context/inject/memories", {}),
    ("get", "/v1/context/inject/hot", {}),
    # P1-3 agent.py 三端点
    ("get", "/v1/agents/ag-1/stats", {}),
    ("get", "/v1/agents/ag-1/constitution", {}),
    ("post", "/v1/agents/ag-1/decision", {"json": {"context": "ctx"}}),
    # P1-4 neurflow_api（router 级代表 + 全部 admin 收口点）
    ("get", "/v1/neurflow/workflows", {}),
    ("post", "/v1/neurflow/nodes/sync", {}),
    ("post", "/v1/neurflow/comfyui/execute", {"json": {"class_type": "TestNode"}}),
    ("post", "/v1/neurflow/agents", {"json": {"name": "n", "role": "r"}}),
    ("post", "/v1/neurflow/agents/ag-1/archive", {}),
    ("post", "/v1/neurflow/agents/ag-1/restore", {}),
    ("post", "/v1/neurflow/executions/ex-1/cancel", {}),
    # P1-5 collaboration_api（router 级代表）
    ("get", "/v1/collaboration/templates", {}),
    ("get", "/v1/collaboration/stats", {}),
    # P1-6 coordination_api（router 级代表 + 五个 reset/clear admin 点）
    ("get", "/coordination/summary", {}),
    ("post", "/coordination/seen-boundary/reset", {}),
    ("post", "/coordination/triage/clear-cache", {}),
    ("post", "/coordination/triage/reset", {}),
    ("post", "/coordination/yield-checker/reset", {}),
    ("post", "/coordination/ab-tests/reset", {}),
    # P2-1 audio.py 五端点
    ("post", "/v1/audio/synthesize", {"json": {"text": "你好"}}),
    ("post", "/v1/audio/synthesize-stream", {"json": {"text": "你好"}}),
    ("post", "/v1/audio/transcribe", {"files": {"audio_file": ("a.wav", b"RIFFxxxx")}}),
    ("get", "/v1/audio/status", {}),
    ("get", "/v1/audio/engines", {}),
    # P2-2 stats.py 五端点
    ("get", "/v1/stats", {}),
    ("get", "/v1/stats/system", {}),
    ("get", "/v1/stats/token-usage", {}),
    ("get", "/v1/stats/usage", {}),
    ("get", "/v1/stats/performance", {}),
    # P2-3 computer_api（心跳无令牌 401；cloud / cleanup-offline 登录门）
    # {computerId} 占位符由测试用种子节点的真实 id 填充。
    ("post", "/v1/computers/{computerId}/heartbeat", {}),
    ("get", "/v1/computers/cloud", {}),
    ("post", "/v1/computers/cleanup-offline", {}),
    # P2-4 session_sync.py
    ("get", "/v1/sync/statistics", {}),
    # P2-5 channels.py
    ("get", "/v1/channel-adapters/health/all", {}),
    ("get", "/v1/channel-adapters/ingress/bypass-stats", {}),
    # P3-7 四处低危
    ("get", "/v1/models/active", {}),
    ("post", "/v1/health/checks/db/run", {}),
    ("post", "/v1/semantic-search/analyze", {"json": {"query": "hello"}}),
    ("post", "/v1/knowledge/access/analyze", {"json": {"query": "hello"}}),
]

# admin 收口点：(method, path, kwargs)。普通用户 403；管理员放行（非 401/403）。
_ADMIN_PROBES = [
    ("post", "/v1/neurflow/nodes/sync", {}),
    ("post", "/v1/neurflow/comfyui/execute", {"json": {"class_type": "TestNode"}}),
    ("post", "/v1/neurflow/agents", {"json": {"name": "n", "role": "r"}}),
    ("post", "/v1/neurflow/agents/ag-1/archive", {}),
    ("post", "/v1/neurflow/agents/ag-1/restore", {}),
    ("post", "/v1/neurflow/executions/ex-1/cancel", {}),
    ("post", "/coordination/seen-boundary/reset", {}),
    ("post", "/coordination/triage/clear-cache", {}),
    ("post", "/coordination/triage/reset", {}),
    ("post", "/coordination/yield-checker/reset", {}),
    ("post", "/coordination/ab-tests/reset", {}),
    ("post", "/v1/computers/cleanup-offline", {}),
]

# 心跳共享令牌的原文（服务端存其 SHA256 摘要，P2-3）。
_DAEMON_PAIR_TOKEN = "pair-secret-2026"
_DAEMON_TOKEN_HASH = hashlib.sha256(_DAEMON_PAIR_TOKEN.encode("utf-8")).hexdigest()

# authed 客户端要覆盖的身份依赖：严格版（auth）、可回退查询参数版（deps 再导出）、
# or_default / or_service 变体——本批各文件从不同入口取用，逐对象覆盖才都生效。
_IDENTITY_DEPS = [
    neurova_auth.get_current_user,
    neurova_auth.get_current_user_or_default,
    neurova_auth.get_current_user_or_service,
    neurova_deps.get_current_user,
]


def _buildApp() -> FastAPI:
    app = FastAPI()
    for module_path, prefix in _TARGET_ROUTERS:
        import importlib

        module = importlib.import_module(module_path)
        app.include_router(module.router, prefix=prefix)
    return app


def _seedDaemonComputer():
    """P2-3：造一台已配对计算节点（服务端持共享令牌摘要）供心跳判据用。"""
    from neurova.collaboration.computer_manager import get_computer_manager_singleton
    from neurova.models.computer import ComputerEngine, ComputerKind

    manager = get_computer_manager_singleton()
    computer = manager.create_computer(
        name="authGuardDaemon",
        owner_user_id=ADMIN["user_id"],
        kind=ComputerKind.LOCAL,
        engine=ComputerEngine.MANAGED,
    )
    computer.daemon_token = _DAEMON_TOKEN_HASH
    return manager, computer.computer_id


@pytest.fixture()
def anonClient():
    """匿名矩阵：不覆盖任何依赖——真身份门真 401。"""
    manager, computer_id = _seedDaemonComputer()
    client = TestClient(_buildApp())
    yield client, computer_id
    try:
        manager.delete_computer(computer_id, hard=True)
    except Exception:  # noqa: BLE001 - 清理失败不影响判据
        pass


@pytest.fixture()
def identityHolder():
    """authed 矩阵：覆盖身份依赖，按需切换 ALICE / ADMIN。"""
    manager, computer_id = _seedDaemonComputer()
    holder = {"user": dict(ALICE)}
    app = _buildApp()
    for dep in _IDENTITY_DEPS:
        app.dependency_overrides[dep] = lambda: holder["user"]
    client = TestClient(app)
    yield client, holder, computer_id
    try:
        manager.delete_computer(computer_id, hard=True)
    except Exception:  # noqa: BLE001
        pass


class TestAuthCoverageGaps:
    def test_anonymousRequestsAreRejected(self, anonClient):
        """匿名（无凭证）访问本批端点一律 401/403，公开清单外不放行。"""
        client, computer_id = anonClient
        leaks = []
        for method, path, kwargs in _ANON_PROBES:
            realPath = path.format(computerId=computer_id)
            resp = getattr(client, method)(realPath, **kwargs)
            if resp.status_code not in (401, 403):
                leaks.append(f"{method.upper()} {realPath} -> {resp.status_code}")
        assert not leaks, "匿名未拦截：\n" + "\n".join(leaks)

    def test_userRoleIsForbiddenOnAdminGates(self, identityHolder):
        """普通用户打 admin 收口点 → 403（角色门咬合）。"""
        client, holder, _computer_id = identityHolder
        holder["user"] = dict(ALICE)
        notBits = []
        for method, path, kwargs in _ADMIN_PROBES:
            resp = getattr(client, method)(path, **kwargs)
            if resp.status_code != 403:
                notBits.append(f"{method.upper()} {path} -> {resp.status_code}")
        assert not notBits, "角色门未拦普通用户：\n" + "\n".join(notBits)

    def test_adminPassesAdminGates(self, identityHolder):
        """管理员打 admin 收口点 → 非 401/403（门已过、进入业务处理）。"""
        client, holder, _computer_id = identityHolder
        holder["user"] = dict(ADMIN)
        blocked = []
        for method, path, kwargs in _ADMIN_PROBES:
            resp = getattr(client, method)(path, **kwargs)
            if resp.status_code in (401, 403):
                blocked.append(f"{method.upper()} {path} -> {resp.status_code}")
        assert not blocked, "管理员被自家门拦下：\n" + "\n".join(blocked)

    def test_decayIsHonest501NotFakeSuccess(self, identityHolder):
        """P2-6：/decay 登录后也必须 501，不再谎报 affected_count:0。"""
        client, holder, _computer_id = identityHolder
        holder["user"] = dict(ADMIN)
        resp = client.post("/v1/enhanced-memory-search/decay")
        assert resp.status_code == 501
        assert "激活衰减未实现" in resp.json()["detail"]

    def test_heartbeatRequiresSharedDaemonToken(self, identityHolder):
        """P2-3：心跳须携带配对共享令牌；登录身份不能替代 daemon 凭证。"""
        client, holder, computer_id = identityHolder
        holder["user"] = dict(ADMIN)
        url = f"/v1/computers/{computer_id}/heartbeat"

        # 登录用户但无 daemon 凭证 → 401（凭证不可省）
        resp = client.post(url)
        assert resp.status_code == 401

        # 错令牌 → 401（不匹配）
        resp = client.post(url, params={"token": "wrong-token"})
        assert resp.status_code == 401

        # 对令牌（原文，服务端现算摘要比对）→ 200
        resp = client.post(url, params={"token": _DAEMON_PAIR_TOKEN})
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

        # 摘要形态同样可过（daemon 直接持 device credential 的形态）
        resp = client.post(url, headers={"Authorization": f"Bearer {_DAEMON_TOKEN_HASH}"})
        assert resp.status_code == 200

    def test_heartbeatAnonymousIs401(self, anonClient):
        """匿名无令牌打心跳 → 401（先于 404 语义前先确认不泄露、不放行）。"""
        client, computer_id = anonClient
        resp = client.post(f"/v1/computers/{computer_id}/heartbeat")
        assert resp.status_code == 401
