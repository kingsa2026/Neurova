"""Wave H-W3 公共库：approve 物化 + 升级提交单型 + /public 真人化

需求映射：公共库（所有用户可见）的写入面——
1. 用户提交（复用既有 submissions 审批流）→ admin approve 时除 catalog
   条目外，**物化进公共库 manifest**（library_service pool=public，
   pool_type=public、owner 空、manifest_source=community）——公共库成为
   装配视图第三层的真实来源；
2. 升级提交（kind=update）：对已上架技能再提新版本不再恒 409，版本号必须
   递增；approve 走 in-place 升级（catalog.update + 公共库条目原地 bump，
   保留 usage/trust 账本——force 重装清零是已登记的坑，绕开）；
3. GET /skill-pool/public 僵尸 dict 改读公共库 manifest（/public/{id} 同）。
"""

import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_p0_fixes_0123456789")

from neurova.api.endpoints import skill_pool_api
from neurova.api.deps import get_current_user
from neurova.skills import library_service as lib
from neurova.skills.market_store import get_market_store, reset_market_store

USER = {"user_id": "u1", "username": "alice", "role": "user", "neuser_id": "u1"}
ADMIN = {"user_id": "a9", "username": "admin", "role": "admin", "neuser_id": "a9"}
BASE = "/api/v1/skill-pool"


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_MARKET_CATALOG", str(tmp_path / "catalog.json"))
    monkeypatch.setenv("NEUROVA_MARKET_SUBMISSIONS", str(tmp_path / "submissions.json"))
    monkeypatch.setenv("NEUROVA_NOTIFICATIONS_PATH", str(tmp_path / "notifications.json"))
    monkeypatch.setattr(lib, "_BASE_DIR", tmp_path)
    lib.reset_libraries_for_tests()
    reset_market_store()

    from neurova.skills.market_submissions import reset_market_submission_store

    reset_market_submission_store()
    import neurova.api.endpoints.notifications as notif_module

    notif_module.reset_notification_manager()
    import neurova.api.endpoints.enhanced_users_api as users_api

    monkeypatch.setattr(
        users_api,
        "_users_store",
        {"a9": {"role": "admin", "username": "admin"}, "u1": {"role": "user", "username": "alice"}},
        raising=False,
    )

    a = FastAPI()
    a.include_router(skill_pool_api.router, prefix=BASE)
    client = TestClient(a, raise_server_exceptions=False)
    return client, tmp_path


def _submit(client, monkeypatch_user=None, **body):
    client.app.dependency_overrides[get_current_user] = lambda: monkeypatch_user or USER
    return client.post(f"{BASE}/skills/submit", json=body)


def _approve_pending(client):
    client.app.dependency_overrides[get_current_user] = lambda: ADMIN
    listing = client.get(f"{BASE}/skill-submissions")
    assert listing.status_code == 200, listing.text
    subs = listing.json()["data"]["items"]
    sub_id = subs[0]["id"] if subs else ""
    assert sub_id, f"无待审单: {listing.json()}"
    return client.post(f"{BASE}/skill-submissions/{sub_id}/review", json={"approve": True})


# ── 1. approve 物化公共库 ──────────────────────────────────


def test_approve_materializes_public_library(app):
    client, tmp = app
    r = _submit(client, skill_id="my-tool", name="My Tool", description="d", version="1.0.0")
    assert r.status_code == 200, r.text
    rr = _approve_pending(client)
    assert rr.status_code == 200, rr.text

    pub = lib.get_library("public")
    info = pub.get_skill_info("my-tool")
    assert info is not None, "approve 后公共库 manifest 必须有条目（装配第三层来源）"
    assert info["manifest"]["source"] == "community"
    entry = pub._skills["my-tool"]
    assert entry["pool_type"] == "public"


def test_catalog_entry_carries_owner(app):
    client, tmp = app
    _submit(client, skill_id="my-tool2", name="T2")
    _approve_pending(client)
    entry = get_market_store().get("my-tool2")
    assert entry.get("owner_user_id") == "u1", "catalog 归属字段吸收（孤岛教训 #3）"


# ── 2. 升级提交单型 ────────────────────────────────────────


def test_update_submission_flow_preserves_ledger(app):
    client, tmp = app
    _submit(client, skill_id="up-tool", name="Up", version="1.0.0")
    _approve_pending(client)
    # 攒点公共账（usage），升级后必须存活
    pub = lib.get_library("public")
    pub.record_skill_funnel("up-tool", selections=5, applications=4, completions=3)

    r2 = _submit(client, skill_id="up-tool", name="Up", version="1.1.0", kind="update")
    assert r2.status_code == 200, r2.text
    rr = _approve_pending(client)
    assert rr.status_code == 200, rr.text

    assert get_market_store().get("up-tool")["version"] == "1.1.0"
    entry = pub.get_skill_info("up-tool")
    assert entry["version"] == "1.1.0"
    assert entry["usage"]["applications"] == 4, "升级必须原地合并：账本不得清零（force 重装坑）"
    # 血缘：修订链追加而非重建
    hist = entry["version_history"]
    assert len(hist) == 2 and hist[1]["parent_revision_id"] == hist[0]["revision_id"]


def test_update_requires_higher_version(app):
    client, tmp = app
    _submit(client, skill_id="ver-tool", name="Ver", version="1.2.0")
    _approve_pending(client)
    r = _submit(client, skill_id="ver-tool", name="Ver", version="1.1.0", kind="update")
    assert r.status_code == 400, "版本未递增的升级提交必须拒绝"


def test_update_on_unknown_skill_rejected(app):
    client, tmp = app
    r = _submit(client, skill_id="ghost-tool", name="Ghost", version="2.0.0", kind="update")
    assert r.status_code == 404


def test_create_conflict_still_guarded(app):
    """kind=create 撞已上架仍 409（旧护栏不回退）。"""
    client, tmp = app
    _submit(client, skill_id="dup-tool", name="Dup", version="1.0.0")
    _approve_pending(client)
    r = _submit(client, skill_id="dup-tool", name="Dup", version="2.0.0")
    assert r.status_code == 409


# ── 3. /public 端点真人化 ──────────────────────────────────


def test_public_endpoints_read_library(app):
    client, tmp = app
    client.app.dependency_overrides[get_current_user] = lambda: USER
    assert client.get(f"{BASE}/public").json() == []
    _submit(client, skill_id="vis-tool", name="Visible", description="desc-x", version="1.0.0")
    _approve_pending(client)
    client.app.dependency_overrides[get_current_user] = lambda: USER
    rows = client.get(f"{BASE}/public").json()
    ids = {r["skill_id"] for r in rows}
    assert "vis-tool" in ids
    one = client.get(f"{BASE}/public/vis-tool")
    assert one.status_code == 200
    assert one.json()["description"] == "desc-x"
    assert client.get(f"{BASE}/public/nope").status_code == 404


# ── 4. V 轮：用户私库来源提交携带可执行载荷（需求 3 全链保可执行）──


def test_pool_skill_submit_carries_exec_payload(app):
    client, tmp = app
    u = lib.get_library("user", "u:u1")
    assert u.register_auto_skill(
        "gen_kit", name="进化套件", description="来自 agent 的合成技能", version="1.4.0",
        config={"tool_sequence": ["web_search", "file_operation"], "category": "研究"},
        manifest_source="auto",
    )
    # 提交面 name/version 故意与库内不符 → 服务端以库内条目为权威覆写
    r = _submit(client, skill_id="kit_pub", name="谎报名", version="9.9.9",
                description="d", pool_skill_id="gen_kit")
    assert r.status_code == 200, r.text
    rr = _approve_pending(client)
    assert rr.status_code == 200, rr.text

    pub = lib.get_library("public")
    info = pub.get_skill_info("kit_pub")
    assert info is not None
    assert info["name"] == "进化套件" and info["version"] == "1.4.0", "库内条目为权威"
    cfg = (info.get("manifest") or {}).get("config") or {}
    assert cfg.get("tool_sequence") == ["web_search", "file_operation"], "可执行载荷进公共库"
    # 装机链闭环：from-public 副本携带 tool_sequence（公共→私库不再退化为元目）
    # （_approve_pending 把鉴权态留在 ADMIN，装机须以 u1 本人身份发起）
    client.app.dependency_overrides[get_current_user] = lambda: USER
    r2 = client.post(f"{BASE}/me/skills/kit_pub/from-public")
    assert r2.status_code == 200, r2.text
    mine = lib.get_library("user", "u:u1").get_skill_info("kit_pub")
    assert ((mine.get("manifest") or {}).get("config") or {}).get("tool_sequence"), "副本可执行"


def test_pool_skill_submit_unknown_id_404(app):
    client, tmp = app
    r = _submit(client, skill_id="x1", name="X", pool_skill_id="ghost-not-in-my-lib")
    assert r.status_code == 404
