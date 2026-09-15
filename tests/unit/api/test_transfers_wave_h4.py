"""Wave H-W4 流转：agent→user 确认推送、同源升级、公共库升级广播

需求映射：
- 需求 3/4（agent 私库→用户私库，初推与升级均经用户确认——拍板"初推也确认"）：
  POST /transfers 提案 → 用户 accept 才 apply_transfer 落副本；
  目标已有同源副本再流转=原地升级（账本/血缘保留）；
- 需求 5（公共库升级→用户/agent 私库副本，用户确认后迭代）：公共库
  update 物化时向持有派生副本的库广播 upgrade 卡；accept 即原地 bump；
- 确认权=目标归属人（dst_owner 的账号）或 admin，他人 403；
- transfer_key 幂等：同源同目标同类型仅一条 pending（防每轮弹卡轰炸）。
"""

import json
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_p0_fixes_0123456789")

from neurova.api.endpoints import skill_pool_api
from neurova.api.deps import get_current_user
from neurova.skills import library_service as lib

USER = {"user_id": "7", "username": "alice", "role": "user", "neuser_id": "7"}
OTHER = {"user_id": "8", "username": "bob", "role": "user", "neuser_id": "8"}
ADMIN = {"user_id": "9", "username": "root", "role": "admin", "neuser_id": "9"}
BASE = "/api/v1/skill-pool"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(lib, "_BASE_DIR", tmp_path)
    lib.reset_libraries_for_tests()
    monkeypatch.setenv("NEUROVA_SKILL_TRANSFERS", str(tmp_path / "transfers.json"))
    monkeypatch.setenv("NEUROVA_NOTIFICATIONS_PATH", str(tmp_path / "notifications.json"))
    from neurova.skills.skill_transfers import reset_skill_transfer_store
    import neurova.api.endpoints.notifications as notif_module

    reset_skill_transfer_store()
    notif_module.reset_notification_manager()

    a = FastAPI()
    a.include_router(skill_pool_api.router, prefix=BASE)
    client = TestClient(a, raise_server_exceptions=False)
    return client, tmp_path


def _as(client, user):
    client.app.dependency_overrides[get_current_user] = lambda: user


def _seed_agent_skill(tmp, skill_id="gen_tool", version="1.0.0", name="Gen Tool"):
    svc = lib.get_library("agent", "myagent")
    svc.register_auto_skill(
        skill_id, name=name, description="进化产物", version=version,
        config={"tool_sequence": ["a", "b"]}, pool_type="agent", owner_user_id="myagent",
    )
    return svc


# ── 1. agent→user 初推（用户确认制）────────────────────────


def test_push_requires_confirmation_then_creates_copy(env):
    client, tmp = env
    _seed_agent_skill(tmp)
    _as(client, USER)
    r = client.post(
        f"{BASE}/transfers",
        json={
            "transfer_type": "agent_to_user",
            "skill_id": "gen_tool",
            "src_pool": "agent",
            "src_owner": "myagent",
        },
    )
    assert r.status_code == 200, r.text
    tid = r.json()["data"]["transfer_id"]
    # 确认前用户库必须无副本
    assert lib.get_library("user", "u:7").get_skill_info("gen_tool") is None
    ra = client.post(f"{BASE}/transfers/{tid}/accept", json={})
    assert ra.status_code == 200, ra.text
    dst = lib.get_library("user", "u:7").get_skill_info("gen_tool")
    assert dst is not None
    assert dst["manifest"]["config"]["transferred_from"] == {
        "pool": "agent", "owner": "myagent", "skill_id": "gen_tool",
    }


def test_transfer_idempotent_pending(env):
    client, tmp = env
    _seed_agent_skill(tmp)
    _as(client, USER)
    body = {"transfer_type": "agent_to_user", "skill_id": "gen_tool", "src_pool": "agent", "src_owner": "myagent"}
    r1 = client.post(f"{BASE}/transfers", json=body).json()["data"]["transfer_id"]
    r2 = client.post(f"{BASE}/transfers", json=body).json()["data"]["transfer_id"]
    assert r1 == r2, "同源同目标 pending 复用（防弹卡轰炸）"


def test_accept_by_other_user_403(env):
    client, tmp = env
    _seed_agent_skill(tmp)
    _as(client, USER)
    tid = client.post(
        f"{BASE}/transfers",
        json={"transfer_type": "agent_to_user", "skill_id": "gen_tool", "src_pool": "agent", "src_owner": "myagent"},
    ).json()["data"]["transfer_id"]
    _as(client, OTHER)
    assert client.post(f"{BASE}/transfers/{tid}/accept", json={}).status_code == 403
    # admin 可代确认
    _as(client, ADMIN)
    assert client.post(f"{BASE}/transfers/{tid}/accept", json={}).status_code == 200


def test_reject_leaves_no_copy(env):
    client, tmp = env
    _seed_agent_skill(tmp)
    _as(client, USER)
    tid = client.post(
        f"{BASE}/transfers",
        json={"transfer_type": "agent_to_user", "skill_id": "gen_tool", "src_pool": "agent", "src_owner": "myagent"},
    ).json()["data"]["transfer_id"]
    assert client.post(f"{BASE}/transfers/{tid}/reject", json={"note": "no"}).status_code == 200
    assert lib.get_library("user", "u:7").get_skill_info("gen_tool") is None


def test_repush_after_source_upgrade_is_inplace(env):
    """同源副本已存在：再次确认=原地升级（账本保留、修订链追加），非重建。"""
    client, tmp = env
    src = _seed_agent_skill(tmp)
    _as(client, USER)
    tid = client.post(
        f"{BASE}/transfers",
        json={"transfer_type": "agent_to_user", "skill_id": "gen_tool", "src_pool": "agent", "src_owner": "myagent"},
    ).json()["data"]["transfer_id"]
    client.post(f"{BASE}/transfers/{tid}/accept", json={})
    dst = lib.get_library("user", "u:7")
    dst.record_skill_funnel("gen_tool", selections=3, applications=3, completions=2)

    src.update_auto_skill("gen_tool", version="1.1.0")
    t2 = client.post(
        f"{BASE}/transfers",
        json={"transfer_type": "agent_to_user", "skill_id": "gen_tool", "src_pool": "agent", "src_owner": "myagent"},
    ).json()["data"]["transfer_id"]
    client.post(f"{BASE}/transfers/{t2}/accept", json={})
    entry = dst.get_skill_info("gen_tool")
    assert entry["version"] == "1.1.0"
    assert entry["usage"]["completions"] == 2, "升级流转不得清零目标账本"


def test_cross_source_same_name_rejected(env):
    """目标副本来自 A 源，B 源同名技能要求流转 → 拒绝顶替。"""
    client, tmp = env
    _seed_agent_skill(tmp, skill_id="gen_tool")
    svc_b = lib.get_library("agent", "otheragent")
    svc_b.register_auto_skill("gen_tool", name="Hijack", pool_type="agent", owner_user_id="otheragent")
    _as(client, USER)
    t1 = client.post(
        f"{BASE}/transfers",
        json={"transfer_type": "agent_to_user", "skill_id": "gen_tool", "src_pool": "agent", "src_owner": "myagent"},
    ).json()["data"]["transfer_id"]
    client.post(f"{BASE}/transfers/{t1}/accept", json={})
    r = client.post(
        f"{BASE}/transfers",
        json={"transfer_type": "agent_to_user", "skill_id": "gen_tool", "src_pool": "agent", "src_owner": "otheragent"},
    )
    assert r.status_code == 200
    tid2 = r.json()["data"]["transfer_id"]
    ra = client.post(f"{BASE}/transfers/{tid2}/accept", json={})
    assert ra.status_code == 409, "异源同名 accept 必须拒绝"
    assert lib.get_library("user", "u:7").get_skill_info("gen_tool")["name"] != "Hijack"


def test_pending_list_scoped_to_owner(env):
    client, tmp = env
    _seed_agent_skill(tmp)
    _as(client, USER)
    client.post(
        f"{BASE}/transfers",
        json={"transfer_type": "agent_to_user", "skill_id": "gen_tool", "src_pool": "agent", "src_owner": "myagent"},
    )
    _as(client, OTHER)
    rows = client.get(f"{BASE}/transfers", params={"status": "pending"}).json()["data"]["items"]
    assert rows == [], "确认队列按目标归属人隔离"
    _as(client, USER)
    mine = client.get(f"{BASE}/transfers", params={"status": "pending"}).json()["data"]["items"]
    assert len(mine) == 1


# ── 2. 公共库升级广播（需求 5）─────────────────────────────


def test_public_upgrade_broadcasts_confirmations(env, monkeypatch):
    client, tmp = env
    # 用户库持有一个"源自公共库"的副本
    user_svc = lib.get_library("user", "u:7")
    user_svc.register_auto_skill(
        "shared_tool", name="Shared", version="1.0.0",
        config={"transferred_from": {"pool": "public", "owner": "", "skill_id": "shared_tool"}},
        manifest_source="community", pool_type="user", owner_user_id="u:7",
    )
    user_svc.record_skill_funnel("shared_tool", selections=2, applications=2, completions=2)

    # 管理员把公共库该技能升级（模拟 approve 物化 update 路径）
    pub = lib.get_library("public")
    pub.register_auto_skill(
        "shared_tool", name="Shared", description="公共版", version="1.0.0",
        manifest_source="community", pool_type="public", owner_user_id="",
    )
    from neurova.api.endpoints.marketplace import _broadcast_public_upgrade

    _broadcast_public_upgrade("shared_tool", "1.2.0", "Shared")

    _as(client, USER)
    rows = client.get(f"{BASE}/transfers", params={"status": "pending"}).json()["data"]["items"]
    ups = [r for r in rows if r.get("kind") == "upgrade" and r.get("src_pool") == "public"]
    assert len(ups) == 1, "公共升级应向持有副本的用户广播确认卡"

    tid = ups[0]["transfer_id"]
    assert client.post(f"{BASE}/transfers/{tid}/accept", json={}).status_code == 200
    entry = user_svc.get_skill_info("shared_tool")
    assert entry["version"] == "1.2.0"
    assert entry["usage"]["completions"] == 2, "公共升级确认后目标副本账本保留"


def test_broadcast_channel_user_key_roundtrip(env):
    """渠道身份用户库（ch:x:y 目录 token）广播反解必须还原合法键：
    旧编码 u_ 反解 replace(_, :, 1) 对 ch: 双冒号产非法键 → dst_owner
    非法、accept 恒 409。V1 %3A 编码的端到端回归锁。"""
    client, tmp = env
    ch_user = "ch:feishu:ou_8899"
    # 目录名即 token：先经 get_library 建立 ch 键用户库并放一个公共来源副本
    ch_svc = lib.get_library("user", ch_user)
    assert ch_svc.skills_dir.parent.name == "ch%3Afeishu%3Aou_8899"
    ch_svc.register_auto_skill(
        "net_tool", name="Net", version="1.0.0",
        config={"transferred_from": {"pool": "public", "owner": "", "skill_id": "net_tool"}},
        manifest_source="community", pool_type="user", owner_user_id=ch_user,
    )
    from neurova.api.endpoints.marketplace import _broadcast_public_upgrade

    # 真实链路=先物化公共库条目再广播（accept 时 apply_transfer 读公共库源）
    pub = lib.get_library("public")
    pub.register_auto_skill(
        "net_tool", name="Net", version="1.1.0", manifest_source="community",
        pool_type="public", owner_user_id="",
    )
    created = _broadcast_public_upgrade("net_tool", "1.1.0", "Net")
    assert created == 1
    _as(client, ADMIN)
    rows = client.get(f"{BASE}/transfers", params={"status": "all"}).json()["data"]["items"]
    # 站内无 ch 账号可登录，走 admin 代确认路径（server 闸：admin 放行）
    card = [r for r in rows if r.get("skill_id") == "net_tool"][0]
    assert card["dst_owner"] == ch_user, "广播反解必须还原完整 ch: 键"
    assert lib.normalize_user_key(card["dst_owner"]) == ch_user
    _as(client, ADMIN)
    r = client.post(f"{BASE}/transfers/{card['transfer_id']}/accept", json={})
    assert r.status_code == 200, f"ch 键副本 accept 不再 409: {r.text}"
    assert ch_svc.get_skill_info("net_tool")["version"] == "1.1.0"
