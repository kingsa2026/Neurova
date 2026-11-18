# -*- coding: utf-8 -*-
"""记忆版本回滚 API 接线（K3）——版本快照从「只写不读」接成闭环

背景：`MemoryVersionControl.rollback_to_version` 全仓零生产调用、零暴露；
`post_chat_pipeline._step_version_snapshot` 每轮为召回记忆写「会话前版本快照
（可回滚保障）」——快照持续积累，但回滚能力用户永不可达（只写不读，断点）。

本档把消费面接上：
- GET  /api/v1/memory/{id}/versions   版本列表（owner/admin）
- POST /api/v1/memory/{id}/rollback   回滚到指定版本（owner/admin，敏感操作写审计）

装配口径与 `test_memory_route_authorization.py` 同款：真 router + 真鉴权依赖 +
真 MemoryManager + 真 MemoryVersionControl，只把 `get_app_state` 换成桩状态——
不为绕过装配点，而是不把整个 app 的启动副作用拖进每条用例。
"""

import types

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.endpoints.memory import router as memoryRouter
from neurova.api.error_handlers import register_error_handlers
from neurova.cognitive_layers.memory_layer.manager import MemoryManager
from neurova.cognitive_layers.memory_layer.version_control import MemoryVersionControl
from tests.auth_headers import bearerHeaders

AGENT_ID = "agent_a"
V1_CONTENT = "K3-V1-原始内容"
V2_CONTENT = "K3-V2-修订内容"


@pytest.fixture
def manager(tmp_path):
    return MemoryManager(db_path=str(tmp_path / "mem.db"), agent_id=AGENT_ID)


@pytest.fixture
def versionControl():
    # 与生产 wire_memory_guards 同口径：内存态版本控制（无 storage 注入）
    return MemoryVersionControl()


@pytest.fixture
def client(manager, versionControl, monkeypatch):
    agent = types.SimpleNamespace(memory_manager=manager, version_control=versionControl)
    state = types.SimpleNamespace(agents={AGENT_ID: agent}, get_agent=lambda *a, **k: agent)
    monkeypatch.setattr("neurova.api.app.get_app_state", lambda: state)

    app = FastAPI()
    register_error_handlers(app)
    app.include_router(memoryRouter, prefix="/api/v1/memory")
    return TestClient(app)


class _AuditRecorder:
    """替身审计单源：只记录，不落库（真单库是进程级单例，测试不写共享盘）。"""

    def __init__(self):
        self.entries = []

    def log(self, entry):
        self.entries.append(entry)
        return True


@pytest.fixture
def auditRecorder(monkeypatch):
    rec = _AuditRecorder()
    monkeypatch.setattr("neurova.security.audit_logger.get_audit_logger", lambda: rec)
    return rec


def _aliceHeaders():
    return bearerHeaders("alice")


def _bobHeaders():
    return bearerHeaders("bob")


def _adminHeaders():
    return bearerHeaders("mallory", role="admin")


def _createMemoryAsAlice(client) -> str:
    r = client.post(
        "/api/v1/memory",
        json={"content": V1_CONTENT, "auto_classify": False},
        headers=_aliceHeaders(),
    )
    assert r.status_code == 200, r.text
    return r.json()["data"]["memory_id"]


def _seedTwoVersions(client, versionControl, memory_id: str):
    """两个版本 + 会话改写：V1 快照 → V2 快照 → 活记忆内容改成 V2。

    与真实场景同形：_step_version_snapshot 先留会话前快照，会话中记忆被改写。
    此后回滚到 V1，活记忆内容必须真的回到 V1——只记一行 ROLLBACK 而不改活
    记忆，不算回滚到位。
    """
    v1 = versionControl.create_snapshot(
        memory_id=memory_id, content=V1_CONTENT, author="k3-test", description="第一版"
    )
    v2 = versionControl.create_snapshot(
        memory_id=memory_id, content=V2_CONTENT, author="k3-test", description="第二版"
    )
    r = client.put(
        f"/api/v1/memory/{memory_id}", json={"content": V2_CONTENT}, headers=_aliceHeaders()
    )
    assert r.status_code == 200, r.text
    return v1.version_id, v2.version_id


class TestMemoryVersionsEndpoint:
    def test_ownerListsVersions(self, client, versionControl):
        memory_id = _createMemoryAsAlice(client)
        v1_id, v2_id = _seedTwoVersions(client, versionControl, memory_id)

        r = client.get(f"/api/v1/memory/{memory_id}/versions", headers=_aliceHeaders())

        assert r.status_code == 200, f"归属者读版本列表应 200，实得 {r.status_code}: {r.text}"
        data = r.json()["data"]
        assert data["memory_id"] == memory_id
        assert data["count"] == 2
        ids = [v["version_id"] for v in data["versions"]]
        assert v1_id in ids and v2_id in ids, f"两个原始版本都应可追溯: {ids}"

    def test_versionsRequireIdentity(self, client, versionControl):
        memory_id = _createMemoryAsAlice(client)
        _seedTwoVersions(client, versionControl, memory_id)

        r = client.get(f"/api/v1/memory/{memory_id}/versions")

        assert r.status_code == 401, f"匿名读版本列表应被身份门拒绝，实得 {r.status_code}"


class TestMemoryRollbackEndpoint:
    def test_rollbackRestoresContentAndKeepsHistory(self, client, versionControl):
        memory_id = _createMemoryAsAlice(client)
        v1_id, v2_id = _seedTwoVersions(client, versionControl, memory_id)

        r = client.post(
            f"/api/v1/memory/{memory_id}/rollback",
            json={"target_version": v1_id},
            headers=_aliceHeaders(),
        )

        assert r.status_code == 200, f"回滚应 200，实得 {r.status_code}: {r.text}"
        body = r.json()["data"]
        assert body["rollback_version"]["version_type"] == "rollback", "应产生 ROLLBACK 快照行"
        assert body["rollback_version"]["metadata"]["rollback_from"] == v1_id
        assert body["rollback_version"]["content"] == V1_CONTENT

        # 内容回到旧版（活记忆，不只是快照行）
        detail = client.get(f"/api/v1/memory/{memory_id}", headers=_aliceHeaders())
        assert detail.status_code == 200, detail.text
        assert detail.json()["data"]["content"] == V1_CONTENT, "回滚后活记忆内容应回到 V1"

        # 原版本仍可追溯：V1/V2 快照行都在，且 ROLLBACK 行可从历史读出
        versions = client.get(f"/api/v1/memory/{memory_id}/versions", headers=_aliceHeaders())
        assert versions.status_code == 200, versions.text
        rows = versions.json()["data"]["versions"]
        ids = {v["version_id"] for v in rows}
        assert {v1_id, v2_id} <= ids, f"原版本必须仍可追溯: {ids}"
        rollback_rows = [v for v in rows if v["version_type"] == "rollback"]
        assert len(rollback_rows) == 1 and rollback_rows[0]["metadata"]["rollback_from"] == v1_id

    def test_rollbackWritesAuditEvent(self, client, versionControl, auditRecorder):
        memory_id = _createMemoryAsAlice(client)
        v1_id, _ = _seedTwoVersions(client, versionControl, memory_id)

        r = client.post(
            f"/api/v1/memory/{memory_id}/rollback",
            json={"target_version": v1_id, "reason": "会话误改，回滚"},
            headers=_aliceHeaders(),
        )

        assert r.status_code == 200, r.text
        assert auditRecorder.entries, "回滚是敏感操作，必须写审计事件"
        entry = auditRecorder.entries[-1]
        assert entry.resource_id == memory_id
        assert entry.user_id == "alice"
        assert "rollback" in (entry.action or "")

    def test_nonOwnerCannotRollback(self, client, versionControl):
        memory_id = _createMemoryAsAlice(client)
        v1_id, _ = _seedTwoVersions(client, versionControl, memory_id)

        r = client.post(
            f"/api/v1/memory/{memory_id}/rollback",
            json={"target_version": v1_id},
            headers=_bobHeaders(),
        )

        assert r.status_code == 404, f"他人回滚应视同不存在，实得 {r.status_code}: {r.text}"
        detail = client.get(f"/api/v1/memory/{memory_id}", headers=_aliceHeaders())
        assert detail.json()["data"]["content"] == V2_CONTENT, "越权回滚不得改动内容"

    def test_adminCanRollbackOthersMemory(self, client, versionControl):
        memory_id = _createMemoryAsAlice(client)
        v1_id, _ = _seedTwoVersions(client, versionControl, memory_id)

        r = client.post(
            f"/api/v1/memory/{memory_id}/rollback",
            json={"target_version": v1_id},
            headers=_adminHeaders(),
        )

        assert r.status_code == 200, f"管理员回滚他人记忆应放行，实得 {r.status_code}: {r.text}"
        # 管理员读他人记忆走带 role 门的管理通道（常规 /{id} 对跨用户作用域恒 404）
        detail = client.get(
            f"/api/v1/memory/management/{memory_id}", headers=_adminHeaders()
        )
        assert detail.status_code == 200, detail.text
        assert detail.json()["data"]["content"] == V1_CONTENT

    def test_rollbackRejectsUnknownTarget(self, client, versionControl):
        memory_id = _createMemoryAsAlice(client)
        _seedTwoVersions(client, versionControl, memory_id)

        r = client.post(
            f"/api/v1/memory/{memory_id}/rollback",
            json={"target_version": "v_missing"},
            headers=_aliceHeaders(),
        )

        assert r.status_code == 404, f"未知目标版本应 404，实得 {r.status_code}: {r.text}"

    def test_rollbackRejectsCrossMemoryTarget(self, client, versionControl):
        memory_a = _createMemoryAsAlice(client)
        _, v2_a = _seedTwoVersions(client, versionControl, memory_a)
        # 另一条记忆 B 与它自己的版本
        r = client.post(
            "/api/v1/memory",
            json={"content": "K3-记忆B", "auto_classify": False},
            headers=_aliceHeaders(),
        )
        memory_b = r.json()["data"]["memory_id"]
        vb = versionControl.create_snapshot(
            memory_id=memory_b, content="K3-记忆B", author="k3-test", description="B 第一版"
        )

        r = client.post(
            f"/api/v1/memory/{memory_a}/rollback",
            json={"target_version": vb.version_id},
            headers=_aliceHeaders(),
        )

        assert r.status_code == 404, f"跨记忆目标版本应 404，实得 {r.status_code}: {r.text}"
        detail = client.get(f"/api/v1/memory/{memory_a}", headers=_aliceHeaders())
        assert detail.json()["data"]["content"] == V2_CONTENT

    def test_rollbackRequiresIdentity(self, client, versionControl):
        memory_id = _createMemoryAsAlice(client)
        v1_id, _ = _seedTwoVersions(client, versionControl, memory_id)

        r = client.post(f"/api/v1/memory/{memory_id}/rollback", json={"target_version": v1_id})

        assert r.status_code == 401, f"匿名回滚应被身份门拒绝，实得 {r.status_code}"
