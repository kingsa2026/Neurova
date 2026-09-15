"""skill_pool_api 鉴权收口 + private 双轨合一（Wave F）

基线巡检坐实的两块债，同源病灶（内存 dict 假持久化 + query 参数当所有权）：

1. **鉴权**：/private CRUD、install-from-url/zip、pending 审批面、agent/{id}/skills
   全部无登录要求（router 无 dependencies，query `agent_id` 直接当凭据）——
   任何未认证请求可用他人 agent_id 读写技能、投递安装、批技能。收口为
   router 级 `Depends(get_current_user)`（对齐 /v1/agents 资源先例：登录即可，
   不做 agent-user 归属表——本系统 agent 是登录用户共享的运行时资产）。

2. **双轨合一**：`_private_skills` 内存 dict（create 写它、list 聚合它、重启即丢、
   update/delete 与磁盘 manifest 互不可见）→ private 链全部落 SkillService
   manifest（SkillService 自身 RLock+原子写承载并发/持久语义）。

3. **share/push 真实现**：share 原是恒成功假象（且前端不传 body 恒 403 之前的
   422）→ 真落盘 config.shared；push/unpush → 条目在源/目标 agent manifest 间
   复制/移除（幂等）。诚实降级：源里查无此技能 → 404。
"""

import json
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_p0_fixes_0123456789")

from neurova.api.deps import get_current_user
from neurova.api.endpoints import skill_pool_api
from neurova.skills.skill_service import SkillService

BASE = "/api/v1/skill-pool"
USER = {"user_id": "u1", "username": "alice", "role": "user", "neuser_id": "u1"}


@pytest.fixture
def env(tmp_path, monkeypatch):
    """隔离 SkillService 落盘目录到 tmp（防测试写真实 data/——EKB 事故教训）。"""
    real_cls = SkillService

    class _TmpService(real_cls):
        def __init__(self, agent_id, skills_dir=None):
            super().__init__(agent_id=agent_id, skills_dir=str(tmp_path / f"agent-{agent_id}"))

    monkeypatch.setattr("neurova.skills.skill_service.SkillService", _TmpService)
    import neurova.api.endpoints.skill_pool_api as spa

    monkeypatch.setattr(spa, "_pool_service", lambda agent_id: _TmpService(agent_id=agent_id), raising=False)

    app = FastAPI()
    app.include_router(skill_pool_api.router, prefix=BASE)
    client = TestClient(app, raise_server_exceptions=False)
    return client, tmp_path


def _authed(client):
    client.app.dependency_overrides[get_current_user] = lambda: USER
    return client


# ── 1. 鉴权覆盖 ────────────────────────────────────────────

UNAUTH_ENDPOINTS = [
    ("GET", f"{BASE}/private?agent_id=victim"),
    ("POST", f"{BASE}/private?agent_id=victim"),
    ("PUT", f"{BASE}/private/whatever?agent_id=victim"),
    ("DELETE", f"{BASE}/private/whatever?agent_id=victim"),
    ("GET", f"{BASE}/agent/victim/skills"),
    ("GET", f"{BASE}/agent/victim/pending-skills"),
    ("POST", f"{BASE}/agent/victim/pending-skills/t1/approve"),
    ("POST", f"{BASE}/agent/victim/pending-experiences/r1/approve"),
]


@pytest.mark.parametrize("method,url", UNAUTH_ENDPOINTS)
def test_endpoints_require_login(method, url, env):
    """无 token → 401（此前全部可未授权读写——router 级鉴权收口）。"""
    client, _ = env
    resp = client.request(method, url, json={} if method in ("POST", "PUT") else None)
    assert resp.status_code == 401, f"{method} {url} 应要求登录，实际 {resp.status_code}"


def test_install_endpoints_require_login(env):
    client, _ = env
    assert client.post(f"{BASE}/install-from-url", json={"url": "http://x/y.zip"}).status_code == 401
    assert client.post(f"{BASE}/install-from-zip").status_code == 401


# ── 2. private 链落盘（双轨合一）───────────────────────────


def test_create_private_persists_to_manifest(env):
    client, tmp_path = env
    _authed(client)
    resp = client.post(f"{BASE}/private?agent_id=a1", json={"name": "s_one", "description": "d", "config": {"k": 1}})
    assert resp.status_code == 200, resp.text
    sid = resp.json()["skill_id"]
    manifest = tmp_path / "agent-a1" / "manifest.json"
    assert manifest.exists(), "create 必须落盘（原内存 dict 重启即丢）"
    entry = json.loads(manifest.read_text(encoding="utf-8"))[sid]
    assert entry["name"] == "s_one"
    assert entry["manifest"]["config"]["k"] == 1


def test_list_private_single_disk_source(env):
    client, _ = env
    _authed(client)
    client.post(f"{BASE}/private?agent_id=a2", json={"name": "persisted"})
    items = client.get(f"{BASE}/private?agent_id=a2").json()
    assert [s["name"] for s in items] == ["persisted"]
    # 别的 agent 看不见（owner 隔离沿用 agent_id 视图过滤）
    assert client.get(f"{BASE}/private?agent_id=a3").json() == []


def test_update_and_delete_hit_disk(env):
    client, tmp_path = env
    _authed(client)
    sid = client.post(f"{BASE}/private?agent_id=a4", json={"name": "before"}).json()["skill_id"]
    r = client.put(f"{BASE}/private/{sid}?agent_id=a4", json={"name": "after", "description": "nd"})
    assert r.status_code == 200
    entry = json.loads((tmp_path / "agent-a4" / "manifest.json").read_text(encoding="utf-8"))[sid]
    assert entry["name"] == "after" and entry["description"] == "nd"
    assert client.delete(f"{BASE}/private/{sid}?agent_id=a4").status_code == 200
    assert sid not in json.loads((tmp_path / "agent-a4" / "manifest.json").read_text(encoding="utf-8"))


def test_update_other_agent_404(env):
    """跨 agent 改技能：源视图查无 → 404（不再 403 假所有权威疑）。"""
    client, _ = env
    _authed(client)
    sid = client.post(f"{BASE}/private?agent_id=owner", json={"name": "mine"}).json()["skill_id"]
    assert client.put(f"{BASE}/private/{sid}?agent_id=attacker", json={"name": "x"}).status_code == 404


# ── 3. share / push 真实化 ─────────────────────────────────


def test_share_persists_flag(env):
    client, tmp_path = env
    _authed(client)
    sid = client.post(f"{BASE}/private?agent_id=a5", json={"name": "sh"}).json()["skill_id"]
    r = client.post(f"{BASE}/private/{sid}/share?agent_id=a5", json={"target_user_id": "bob"})
    assert r.status_code == 200
    cfg = json.loads((tmp_path / "agent-a5" / "manifest.json").read_text(encoding="utf-8"))[sid]["manifest"]["config"]
    assert cfg["shared"] is True and cfg["shared_with"] == ["bob"]


def test_push_copies_to_target_agent(env):
    client, tmp_path = env
    _authed(client)
    sid = client.post(f"{BASE}/private?agent_id=src", json={"name": "pushed", "config": {"x": 1}}).json()["skill_id"]
    r = client.post(f"{BASE}/private/{sid}/push?agent_id=src", json={"agent_id": "dst"})
    assert r.status_code == 200, r.text
    dst = json.loads((tmp_path / "agent-dst" / "manifest.json").read_text(encoding="utf-8"))
    assert dst[sid]["name"] == "pushed" and dst[sid]["manifest"]["config"]["x"] == 1
    # 幂等重推
    assert client.post(f"{BASE}/private/{sid}/push?agent_id=src", json={"agent_id": "dst"}).status_code == 200
    # unpush 移除
    assert client.delete(f"{BASE}/private/{sid}/push?agent_id=dst").status_code == 200
    assert sid not in json.loads((tmp_path / "agent-dst" / "manifest.json").read_text(encoding="utf-8"))


def test_push_unknown_skill_404(env):
    client, _ = env
    _authed(client)
    assert client.post(f"{BASE}/private/ghost/push?agent_id=src", json={"agent_id": "dst"}).status_code == 404


# ── 4. 存量测试兼容护栏：公开面不回归 ─────────────────────


def test_public_list_still_empty_ok(env):
    client, _ = env
    _authed(client)
    assert client.get(f"{BASE}/public").status_code == 200
