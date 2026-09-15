"""闭环核验轮（V4）：/skill-pool/me/skills 用户私库真人面

前端"技能库"页私有页签此前调 GET /private?agent_id=_all——落到幽灵
data/agents/_all 桶且公共/私有列表因裸数组 vs res.data 解包错位恒空。
三层语义下的正解：该页私有页签=当前账号的用户私库（pool=user, ukey=
u:{user_id}），新增 /me/skills CRUD + /me/skills/{id}/from-public 自助安装
（"市场安装落用户库"定案在本页的落地；不动 marketplace 既有 agent 安装面）。
- 需求 1：用户私库对用户本人可见可管；
- 需求 3/5 的接受端与本页确认队列（transfers）同库——装/推/升全在 u:{id} 桶闭环。
"""

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
    client.app.dependency_overrides[get_current_user] = lambda: USER
    return client, tmp_path


def _as(client, user):
    client.app.dependency_overrides[get_current_user] = lambda: user


def test_me_crud_lands_in_user_library(env):
    client, tmp = env
    # 空库
    assert client.get(f"{BASE}/me/skills").json() == []
    # 创建 → 用户库
    r = client.post(f"{BASE}/me/skills", json={"name": "我的整理", "description": "d", "category": "工具"})
    assert r.status_code == 200, r.text
    sid = r.json()["skill_id"]
    listed = client.get(f"{BASE}/me/skills").json()
    assert [s["skill_id"] for s in listed] == [sid]
    assert listed[0]["scope"] == "user" and listed[0]["owner_id"] == "u:7"
    # 落盘目录=u%3A7（%3A token）
    assert (tmp / "users" / "u%3A7" / "skills" / "manifest.json").exists()
    # 更新
    r = client.put(f"{BASE}/me/skills/{sid}", json={"name": "改名了"})
    assert r.status_code == 200 and client.get(f"{BASE}/me/skills").json()[0]["name"] == "改名了"
    # 删除
    assert client.delete(f"{BASE}/me/skills/{sid}").status_code == 200
    assert client.get(f"{BASE}/me/skills").json() == []
    assert client.put(f"{BASE}/me/skills/{sid}", json={"name": "x"}).status_code == 404
    assert client.delete(f"{BASE}/me/skills/{sid}").status_code == 404


def test_me_libraries_isolated_between_accounts(env):
    client, tmp = env
    sid = client.post(f"{BASE}/me/skills", json={"name": "A库"}).json()["skill_id"]
    _as(client, OTHER)
    assert client.get(f"{BASE}/me/skills").json() == []
    assert client.delete(f"{BASE}/me/skills/{sid}").status_code == 404, "他人库条目按 404 处理（防枚举）"
    _as(client, USER)
    assert client.get(f"{BASE}/me/skills").json()[0]["skill_id"] == sid


def test_install_from_public_lands_in_my_library(env):
    client, tmp = env
    pub = lib.get_library("public")
    pub.register_auto_skill(
        "csv_kit", name="CSV 套件", description="公共", version="1.0.0",
        config={"category": "数据"}, manifest_source="community",
        pool_type="public", owner_user_id="",
    )
    r = client.post(f"{BASE}/me/skills/csv_kit/from-public")
    assert r.status_code == 200, r.text
    mine = client.get(f"{BASE}/me/skills").json()
    assert [s["skill_id"] for s in mine] == ["csv_kit"]
    assert mine[0]["version"] == "1.0.0"
    # 血缘写入 → 公共升级广播可达（需求 5 闭环）
    info = lib.get_library("user", "u:7").get_skill_info("csv_kit")
    tf = (info.get("manifest") or {}).get("config", {}).get("transferred_from")
    assert tf and tf["pool"] == "public"
    # 重复安装=原地升级（不报错不重复）
    pub.update_auto_skill("csv_kit", version="2.0.0")
    assert client.post(f"{BASE}/me/skills/csv_kit/from-public").status_code == 200
    assert client.get(f"{BASE}/me/skills").json()[0]["version"] == "2.0.0"
    # 无此公共技能 → 404
    assert client.post(f"{BASE}/me/skills/nope/from-public").status_code == 404


def test_from_public_refused_over_local_same_name(env):
    """本地同名技能（无血缘）不被安装顶替——apply_transfer V2 闸的 API 面。"""
    client, tmp = env
    client.post(f"{BASE}/me/skills", json={"name": "本地同名"})
    # 本地条目是 uuid sid；直接以同 sid 造公共条目
    sid = client.get(f"{BASE}/me/skills").json()[0]["skill_id"]
    pub = lib.get_library("public")
    pub.register_auto_skill(sid, name="公共同名", pool_type="public", owner_user_id="")
    r = client.post(f"{BASE}/me/skills/{sid}/from-public")
    assert r.status_code == 409


def test_enabled_toggle_is_row_level(env, monkeypatch):
    """V5：启停必须触发行级 enabled（消费方 call_skill/注册表读条目 enabled），
    旧通道把开关塞进 manifest.config.enabled 是静默空操作。"""
    client, tmp = env
    sid = client.post(f"{BASE}/me/skills", json={"name": "开关技能"}).json()["skill_id"]
    r = client.put(f"{BASE}/me/skills/{sid}", json={"enabled": False})
    assert r.status_code == 200 and r.json()["enabled"] is False
    mine = client.get(f"{BASE}/me/skills").json()
    assert mine[0]["enabled"] is False
    # 行级落盘（不是 config 假通道）
    import json as _json

    raw = _json.loads((tmp / "users" / "u%3A7" / "skills" / "manifest.json").read_text(encoding="utf-8"))
    assert raw[sid]["enabled"] is False


def test_private_execute_route(env, tmp_path, monkeypatch):
    """V5：/private/{id}/execute 路由补齐（AgentSkillPage 执行按钮此前恒 404）。"""
    client, _tmp = env
    from neurova.skills import library_service as _lib

    # _pool_service 重定向到 tmp 下的 agent 库（防污染真 data/）
    monkeypatch.setattr(
        skill_pool_api, "_pool_service",
        lambda agent_id: _lib.get_library("agent", agent_id),
    )
    src = tmp_path / "echosrc"
    src.mkdir()
    (src / "manifest.json").write_text('{"id": "echo", "name": "Echo", "version": "1.0.0"}', encoding="utf-8")
    (src / "main.py").write_text("def main(message='hi'):\n    return {'echo': message}\n", encoding="utf-8")
    svc = _lib.get_library("agent", "ax")
    assert svc.install_skill(str(src), skill_id="echo").get("success") is True

    r = client.post(f"{BASE}/private/echo/execute", json={"agent_id": "ax", "arguments": {"message": "yo"}})
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["success"] is True and data["result"]["echo"] == "yo"
    # 禁用后执行被行级闸拒绝（update 端点以 query agent_id 定位库）
    assert client.put(f"{BASE}/private/echo", params={"agent_id": "ax"}, json={"enabled": False}).status_code == 200
    r2 = client.post(f"{BASE}/private/echo/execute", json={"agent_id": "ax", "arguments": {}})
    assert r2.json()["data"]["success"] is False and "disabled" in str(r2.json()["data"]["error"])
    # 不存在 → 404
    assert client.post(f"{BASE}/private/ghost/execute", json={"agent_id": "ax"}).status_code == 404


def test_install_target_routing(env):
    """V 轮：导入落点路由决策单测（default/agent=现状 default agent 库零变化；
    me=当前账号用户私库）。"""
    client, tmp = env
    svc, pool, owner = skill_pool_api._install_target(None, USER)
    assert pool == "agent" and owner == "default"
    assert str(svc.skills_dir).replace("\\", "/").endswith("agents/default/skills")
    svc2, pool2, owner2 = skill_pool_api._install_target("me", USER)
    assert pool2 == "user" and owner2 == "u:7"
    assert "users/u%3A7/skills" in str(svc2.skills_dir).replace("\\", "/")


# ── 导入落点必须在两条 HTTP 导入链上真生效（85ba8aa7 回归）────────────
# 根因：V 轮把落点解析抽成 _install_target 后，/install-from-url 改用了它，
# /install-from-zip 仍调用**不存在的** _install_target_service → NameError 被
# 函数兜底 except Exception 吞成 {"success": false, "error": "name ... is not
# defined"}，端点恒 200 假失败。helper 单测（上一条）看不到调用点错位。


def _skill_zip(skill_id: str) -> bytes:
    """最小可安装技能 zip（manifest.json + 干净 SKILL.md，过安装门）。"""
    import io
    import json as _json
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("manifest.json", _json.dumps({"id": skill_id, "name": skill_id, "version": "1.0.0"}))
        zf.writestr("SKILL.md", "# helper\n\n把日期格式化为 ISO 标准格式的技能说明。\n")
    return buf.getvalue()


def test_install_from_zip_default_target_lands_in_agent_library(env):
    """默认 target：落 agent 库（default），且不得再出现假失败 payload。"""
    client, tmp = env
    r = client.post(
        f"{BASE}/install-from-zip",
        files={"file": ("zipdemo.zip", _skill_zip("zipdemo"), "application/zip")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("success") is True, body
    assert lib.get_library("agent", "default").get_skill_info("zipdemo") is not None
    assert (tmp / "agents" / "default" / "skills" / "manifest.json").exists()


def test_install_from_zip_target_me_lands_in_user_library(env):
    """target=me：落当前账号用户私库（u:7），不可落到 agent 库。"""
    client, tmp = env
    r = client.post(
        f"{BASE}/install-from-zip",
        data={"target": "me"},
        files={"file": ("zipmine.zip", _skill_zip("zipmine"), "application/zip")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("success") is True, body
    assert (tmp / "users" / "u%3A7" / "skills" / "manifest.json").exists()
    assert lib.get_library("user", "u:7").get_skill_info("zipmine") is not None
    assert lib.get_library("agent", "default").get_skill_info("zipmine") is None
