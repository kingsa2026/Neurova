"""
公共技能 删除语义 防回归测试（2026-09-01，同知识库连坐删除 bug 的同类排查）

背景：知识库的公共条目与私人条目是同一份物理数据（submit-public 仅改
visibility），admin 物理删除会连坐删掉属主数据——已修复为语义分流
（默认下架，purge=true 才物理删）。

本文件核查并钉住技能市场侧的等价契约。技能市场与知识库的数据模型不同：
市场目录（catalog.json）、安装副本（skills_dir/{skill_id}）、提交单
（submissions.json）是三份独立存储。契约：

1. admin 从市场目录下架（DELETE /skills/{id}）→ 只删目录条目，
   已安装副本不受影响（用户装过的还能用）。
2. 用户卸载（DELETE /skills/{id}/install）→ 只删安装副本，
   市场目录条目仍在（还能再装/别人还能装）。
3. 提交单被拒绝/下架后，市场目录与安装副本均不联动删除
   （审批动作只改提交单状态；approve 时才写入目录）。
"""
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_p0_fixes_0123456789")

from neurova.api.deps import get_current_user
from neurova.api.endpoints import marketplace, notifications as notif_module
from neurova.skills.market_store import reset_market_store

USER = {"user_id": "u1", "username": "alice", "role": "user", "neuser_id": "u1"}
ADMIN = {"user_id": "a9", "username": "admin", "role": "admin", "neuser_id": "a9"}

BASE = "/api/v1/marketplace"


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_MARKET_CATALOG", str(tmp_path / "catalog.json"))
    monkeypatch.setenv("NEUROVA_MARKET_SUBMISSIONS", str(tmp_path / "submissions.json"))
    monkeypatch.setenv("NEUROVA_NOTIFICATIONS_PATH", str(tmp_path / "notifications.json"))
    reset_market_store()
    notif_module.reset_notification_manager()

    # 隔离 importer 单例：安装副本落在 tmp_path/skills（固定实例——
    # install/uninstall 必须共享 _installed 状态）
    from neurova.skills import market_importer

    _importer = market_importer.MarketImporter(skills_dir=tmp_path / "skills")
    monkeypatch.setattr(
        "neurova.api.endpoints.marketplace.get_market_importer",
        lambda: _importer,
    )

    import neurova.api.endpoints.enhanced_users_api as users_api

    monkeypatch.setattr(
        users_api,
        "_users_store",
        {"a9": {"role": "admin", "username": "admin"}, "u1": {"role": "user", "username": "alice"}},
        raising=False,
    )

    a = FastAPI()
    a.include_router(marketplace.router, prefix=BASE)
    with TestClient(a, raise_server_exceptions=False) as c:
        yield a, c, tmp_path / "skills"
    reset_market_store()
    notif_module.reset_notification_manager()


def _auth(c, role):
    user = ADMIN if role == "admin" else USER
    c.app.dependency_overrides[get_current_user] = lambda: user
    return c


def _install(c, skills_dir, skill_id="web-search"):
    """走真实安装链路（本地种子条目 → skills_dir/{skill_id}）。"""
    r = c.post(f"{BASE}/skills/{skill_id}/install", json={})
    assert r.status_code == 200, r.text[:200]
    assert (skills_dir / skill_id / "skill.json").exists(), "安装应落副本"
    return skills_dir / skill_id


class TestMarketDeleteSemantics:
    def test_admin_remove_from_catalog_keeps_installed_copy(self, app):
        """下架 ≠ 卸载：目录删除后已安装副本必须保留。"""
        _a, c, skills_dir = app
        _auth(c, "user")
        _install(c, skills_dir)

        _auth(c, "admin")
        r = c.delete(f"{BASE}/skills/web-search")
        assert r.status_code == 200

        assert (skills_dir / "web-search" / "skill.json").exists(), (
            "市场下架不得删除用户已安装副本（连坐删除同类 bug 防回归）"
        )

    def test_uninstall_keeps_catalog_entry(self, app):
        """卸载 ≠ 下架：卸载后市场目录条目保留（可再装）。"""
        _a, c, skills_dir = app
        _auth(c, "user")
        _install(c, skills_dir)

        r = c.delete(f"{BASE}/skills/web-search/install")
        assert r.status_code == 200
        assert not (skills_dir / "web-search").exists(), "卸载应删除安装副本"

        _auth(c, "admin")
        from neurova.skills.market_store import get_market_store

        assert get_market_store().get("web-search") is not None, "卸载不得动市场目录"

    def test_submission_reject_touches_neither_catalog_nor_install(self, app):
        """拒绝提交单：只改提交单状态，目录/安装副本零联动。"""
        _a, c, skills_dir = app
        _auth(c, "user")
        r = c.post(
            f"{BASE}/skills/submit",
            json={"skill_id": "sub-1", "name": "Sub One", "version": "1.0.0"},
        )
        assert r.status_code == 200
        sub_id = r.json()["data"]["id"]

        _auth(c, "user")
        _install(c, skills_dir, skill_id="web-search")  # 无关技能，验证零误伤

        _auth(c, "admin")
        r = c.post(f"{BASE}/skill-submissions/{sub_id}/review", json={"approve": False})
        assert r.status_code == 200

        from neurova.skills.market_store import get_market_store

        assert get_market_store().get("sub-1") is None, "拒绝后不得上架"
        assert (skills_dir / "web-search" / "skill.json").exists(), "审批动作不得误删安装副本"
