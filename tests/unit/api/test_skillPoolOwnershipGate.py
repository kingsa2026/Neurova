# -*- coding: utf-8 -*-
"""PLUG-04（2026-11-25 全仓审计·批次C）：技能池缺归属门。

审计实形（以当前代码复核）：
- GET /agent/{id}/skills、GET /agent/{id}/domain-harnesses：仅登录即可读任意
  Agent 的技能库（`_require_agent_access` 已是仓内单源门，这两面漏挂）；
- POST /install-from-url、/install-from-zip target=agent：任何登录用户可写
  共享的 default Agent 库；
- POST /transfers：src_owner 由请求体自带且不校验归属——任何人可把他人
  Agent 的技能发起流转到自己名下（确认人=自己，等于搬走）；
- 待审经验面读的是**全局**经验库：门只看路径 agent_id，数据不按 Agent
  收敛——他人 Agent 的待审经验可读、可批、可拒。

修复方向（审计建议）：全部池操作过 `_require_agent_access`（agent_access
单源门，R6 直接复用）；transfers 校验 src_owner 归属调用者；待审经验按
Agent 技能账本收敛。
"""

import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_p0_fixes_0123456789")

from neurova.api.endpoints import skill_pool_api
from tests.auth_headers import overrideIdentity

BASE = "/api/v1/skill-pool"
USER = {"user_id": "7", "username": "alice", "role": "user", "neuser_id": "7"}
OTHER = {"user_id": "8", "username": "bob", "role": "user", "neuser_id": "8"}
ADMIN = {"user_id": "9", "username": "root", "role": "admin", "neuser_id": "9"}

#: 归属登记：a1 属 USER(7)，a2 属 OTHER(8)；default 无主（仅 admin）。
_OWNERS = {"a1": "7", "a2": "8"}


@pytest.fixture
def env(tmp_path, monkeypatch):
    from neurova.skills import library_service as lib

    monkeypatch.setattr(lib, "_BASE_DIR", tmp_path)
    monkeypatch.setenv("NEUROVA_AGENT_WORKSPACES_DIR", str(tmp_path))
    lib.reset_libraries_for_tests()
    monkeypatch.setenv("NEUROVA_SKILL_TRANSFERS", str(tmp_path / "transfers.json"))
    monkeypatch.setenv("NEUROVA_NOTIFICATIONS_PATH", str(tmp_path / "notifications.json"))
    from neurova.skills.skill_transfers import reset_skill_transfer_store
    import neurova.api.endpoints.notifications as notif_module

    reset_skill_transfer_store()
    notif_module.reset_notification_manager()
    from neurova.evolution.skill_experience import reset_skill_experience_store

    reset_skill_experience_store()

    # 归属单源的中枢登记面替身：走生产 _agent_owner 的真实回退链取属主
    class _FakeRegistry:
        def get_agent(self, agent_id):
            owner = _OWNERS.get(agent_id)
            return {"owner_user_id": owner} if owner else None

    import neurova.api.endpoints.agent as agent_mod

    monkeypatch.setattr(agent_mod, "get_agent_config_manager", lambda: _FakeRegistry())

    app = FastAPI()
    app.include_router(skill_pool_api.router, prefix=BASE)
    client = TestClient(app, raise_server_exceptions=False)
    yield client, tmp_path
    lib.reset_libraries_for_tests()
    reset_skill_transfer_store()
    notif_module.reset_notification_manager()
    reset_skill_experience_store()


def _seed_agent_skill(tmp, agent_id="a1", skill_id="gen_tool"):
    from neurova.skills import library_service as lib

    svc = lib.get_library("agent", agent_id)
    svc.register_auto_skill(
        skill_id, name="Gen Tool", description="进化产物", version="1.0.0",
        config={"tool_sequence": ["a", "b"]}, pool_type="agent", owner_user_id=agent_id,
        manifest_source="user",  # 夹具造数：auto 源会被创作门按无证据拒收
    )
    return svc


def _seed_pending_experience(skill_id: str, content: str) -> str:
    """经生产写入口进全局待审队列（评审闸默认开，improver 源必进待审）。"""
    from neurova.evolution.skill_experience import get_skill_experience_store

    record = get_skill_experience_store().record_experience(
        skill_id, content, source="improver", context="ctx")
    assert record is not None
    return record.record_id


# ── 1. Agent 技能读取面 ────────────────────────────────────


def test_agent_skills_other_user_403(env):
    """他人 Agent 的技能列表 → 403（修复前：200 全量读出）。"""
    client, tmp = env
    _seed_agent_skill(tmp, "a1", "gen_tool")
    overrideIdentity(client.app, OTHER)
    r = client.get(f"{BASE}/agent/a1/skills")
    assert r.status_code == 403, f"实际 {r.status_code}: {r.text[:160]}"


def test_agent_skills_owner_200(env):
    client, tmp = env
    _seed_agent_skill(tmp, "a1", "gen_tool")
    overrideIdentity(client.app, USER)
    r = client.get(f"{BASE}/agent/a1/skills")
    assert r.status_code == 200, r.text
    assert [s["skill_id"] for s in r.json()] == ["gen_tool"]


def test_agent_skills_admin_200(env):
    client, tmp = env
    _seed_agent_skill(tmp, "a1", "gen_tool")
    overrideIdentity(client.app, ADMIN)
    assert client.get(f"{BASE}/agent/a1/skills").status_code == 200


def test_agent_skills_unauth_401(env):
    client, _ = env
    assert client.get(f"{BASE}/agent/a1/skills").status_code == 401


def test_domain_harnesses_other_user_403(env):
    """他人 Agent 的 harness 检索 → 403（修复前：200）。"""
    client, tmp = env
    _seed_agent_skill(tmp, "a1", "gen_tool")
    overrideIdentity(client.app, OTHER)
    r = client.get(f"{BASE}/agent/a1/domain-harnesses")
    assert r.status_code == 403, f"实际 {r.status_code}: {r.text[:160]}"


def test_domain_harnesses_owner_200(env):
    client, tmp = env
    _seed_agent_skill(tmp, "a1", "gen_tool")
    overrideIdentity(client.app, USER)
    assert client.get(f"{BASE}/agent/a1/domain-harnesses").status_code == 200


# ── 2. default Agent 库安装面 ──────────────────────────────


def test_install_from_url_other_user_403(env):
    """target=agent（default 库）对非属主/管理员 → 403（修复前：200 进入安装链）。"""
    client, tmp = env
    overrideIdentity(client.app, OTHER)
    r = client.post(f"{BASE}/install-from-url", json={"url": "http://x.invalid/y.zip"})
    assert r.status_code == 403, f"实际 {r.status_code}: {r.text[:160]}"


def test_install_from_zip_other_user_403(env):
    client, tmp = env
    overrideIdentity(client.app, OTHER)
    r = client.post(
        f"{BASE}/install-from-zip",
        files={"file": ("x.zip", b"PK\x03\x04", "application/zip")},
        data={"target": ""},
    )
    assert r.status_code == 403, f"实际 {r.status_code}: {r.text[:160]}"


def test_install_from_url_admin_200(env, monkeypatch):
    """管理员放行（反向控制格：门不误伤 admin 的安装链）。"""
    client, tmp = env
    overrideIdentity(client.app, ADMIN)
    from unittest.mock import MagicMock

    stub = MagicMock()
    stub.install_skill.return_value = {"success": True, "skill_id": "x"}
    monkeypatch.setattr(skill_pool_api, "_pool_service", lambda *a, **kw: stub)
    r = client.post(f"{BASE}/install-from-url", json={"url": "http://x.invalid/y.zip"})
    assert r.status_code == 200, r.text
    assert r.json().get("success") is True


def test_install_from_zip_me_target_no_agent_gate(env):
    """target=me 落自己用户私库，不设 agent 门（正向：本人可用）。"""
    client, tmp = env
    overrideIdentity(client.app, USER)
    import io
    import json as _json
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("manifest.json", _json.dumps({"id": "mine1", "name": "mine1", "version": "1.0.0"}))
        zf.writestr("SKILL.md", "# helper\n\n把日期格式化为 ISO 标准格式的技能说明。\n")
    r = client.post(
        f"{BASE}/install-from-zip",
        files={"file": ("mine1.zip", buf.getvalue(), "application/zip")},
        data={"target": "me"},
    )
    assert r.status_code == 200, r.text
    assert r.json().get("success") is True, r.text


# ── 3. 流转 src_owner 归属 ─────────────────────────────────

_TRANSFER_BODY = {
    "transfer_type": "agent_to_user",
    "skill_id": "gen_tool",
    "src_pool": "agent",
}


def test_transfer_from_others_agent_403(env):
    """src_owner=他人 Agent → 403（修复前：200 建卡，确认人还是自己）。"""
    client, tmp = env
    _seed_agent_skill(tmp, "a1", "gen_tool")
    overrideIdentity(client.app, OTHER)
    r = client.post(f"{BASE}/transfers", json={**_TRANSFER_BODY, "src_owner": "a1"})
    assert r.status_code == 403, f"实际 {r.status_code}: {r.text[:160]}"


def test_transfer_from_own_agent_ok(env):
    """属主发起自己 Agent 的流转 → 200（正向控制格）。"""
    client, tmp = env
    _seed_agent_skill(tmp, "a1", "gen_tool")
    overrideIdentity(client.app, USER)
    r = client.post(f"{BASE}/transfers", json={**_TRANSFER_BODY, "src_owner": "a1"})
    assert r.status_code == 200, r.text
    assert r.json()["code"] == 0


def test_transfer_admin_any_agent_ok(env):
    client, tmp = env
    _seed_agent_skill(tmp, "a1", "gen_tool")
    overrideIdentity(client.app, ADMIN)
    r = client.post(f"{BASE}/transfers", json={**_TRANSFER_BODY, "src_owner": "a1"})
    assert r.status_code == 200, r.text


def test_transfer_from_other_user_pool_403(env):
    """src_pool=user 且 src_owner=他人账号 → 403（修复前：200 建卡）。"""
    client, tmp = env
    from neurova.skills import library_service as lib

    lib.get_library("user", "u:8").register_auto_skill(
        "u_tool", name="U Tool", manifest_source="user", pool_type="user",
        owner_user_id="u:8")
    overrideIdentity(client.app, USER)
    r = client.post(f"{BASE}/transfers", json={
        "transfer_type": "agent_to_user", "skill_id": "u_tool",
        "src_pool": "user", "src_owner": "u:8",
    })
    assert r.status_code == 403, f"实际 {r.status_code}: {r.text[:160]}"


def test_transfer_from_own_user_pool_ok(env):
    client, tmp = env
    from neurova.skills import library_service as lib

    lib.get_library("user", "u:7").register_auto_skill(
        "u_tool", name="U Tool", manifest_source="user", pool_type="user",
        owner_user_id="u:7")
    overrideIdentity(client.app, USER)
    r = client.post(f"{BASE}/transfers", json={
        "transfer_type": "agent_to_user", "skill_id": "u_tool",
        "src_pool": "user", "src_owner": "u:7",
    })
    assert r.status_code == 200, r.text


# ── 4. 待审经验按 Agent 收敛 ───────────────────────────────


def test_pending_experiences_scoped_to_agent(env):
    """他人 Agent 技能的待审经验不出现在本 Agent 的待审列表（修复前：全局全吐）。"""
    client, tmp = env
    _seed_agent_skill(tmp, "a1", "s_mine")
    mine_id = _seed_pending_experience("s_mine", "只属于 a1 的经验")
    _seed_pending_experience("s_other", "别人家技能的经验")
    overrideIdentity(client.app, USER)
    r = client.get(f"{BASE}/agent/a1/pending-experiences")
    assert r.status_code == 200, r.text
    ids = [row["record_id"] for row in r.json()]
    assert ids == [mine_id], f"待审经验未按 Agent 收敛: {ids}"


def test_pending_experience_approve_scoped_to_agent(env):
    """批准他人 Agent 技能的待审经验 → 404（修复前：200 批准生效）。"""
    client, tmp = env
    _seed_agent_skill(tmp, "a1", "s_mine")
    _seed_pending_experience("s_mine", "自己的经验")
    other_id = _seed_pending_experience("s_other", "别人家技能的经验")
    overrideIdentity(client.app, USER)
    r = client.post(f"{BASE}/agent/a1/pending-experiences/{other_id}/approve")
    assert r.status_code == 404, f"实际 {r.status_code}: {r.text[:160]}"


def test_pending_experience_reject_scoped_to_agent(env):
    client, tmp = env
    _seed_agent_skill(tmp, "a1", "s_mine")
    _seed_pending_experience("s_mine", "自己的经验")
    other_id = _seed_pending_experience("s_other", "别人家技能的经验")
    overrideIdentity(client.app, USER)
    r = client.post(f"{BASE}/agent/a1/pending-experiences/{other_id}/reject")
    assert r.status_code == 404, f"实际 {r.status_code}: {r.text[:160]}"
