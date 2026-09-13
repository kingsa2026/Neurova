"""核验 — /agent/{id}/skills 与 /agent/{id}/pending-skills 路由分离。

根因:装饰器堆叠使两个路径都指向 list_pending_skills(闸关时恒 []),
真正的 get_agent_skills(SkillService 列表)从未注册——前端技能页断链。
本测试锁定两条路径各自的行为,防回归。
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.deps import get_current_user
from neurova.api.endpoints import skill_pool_api

BASE = "/api/v1/skill-pool"
USER = {"user_id": "u1", "username": "alice", "role": "user", "neuser_id": "u1"}


@pytest.fixture
def client(monkeypatch):
    app = FastAPI()
    app.include_router(skill_pool_api.router, prefix=BASE)
    with TestClient(app, raise_server_exceptions=False) as c:
        c.app.dependency_overrides[get_current_user] = lambda: USER
        yield c


class TestSkillsRouteSeparation:
    def test_skills_path_uses_skill_service(self, client, monkeypatch):
        import neurova.skills.skill_service as ss

        monkeypatch.setattr(ss.SkillService, "__init__", lambda self, **kw: None)
        monkeypatch.setattr(ss.SkillService, "list_skills", lambda self, **kw: [
            {"id": "s1", "name": "Skill One", "description": "d", "version": "1.0.0",
             "enabled": True, "usage": {"state": "active", "use_count": 3, "pinned": True}},
        ])
        r = client.get(f"{BASE}/agent/a1/skills")
        assert r.status_code == 200
        items = r.json()
        assert items[0]["skill_id"] == "s1"
        assert items[0]["usage"]["state"] == "active"
        assert items[0]["usage"]["pinned"] is True

    def test_pending_path_uses_packer_not_service(self, client, monkeypatch):
        """pending-skills 路径必须仍走 packer(审批面),不被技能列表顶替。"""
        import neurova.api.endpoints.governance as gov
        import neurova.skills.skill_service as ss

        called = {"skills": False}

        def fake_list(self, **kw):
            called["skills"] = True
            return []

        monkeypatch.setattr(ss.SkillService, "__init__", lambda self, **kw: None)
        monkeypatch.setattr(ss.SkillService, "list_skills", fake_list)
        agent = type("A", (), {"skill_packer": None})()
        monkeypatch.setattr(gov, "_get_agent", lambda: agent)
        r = client.get(f"{BASE}/agent/a1/pending-skills")
        assert r.status_code == 200 and r.json() == []
        assert not called["skills"], "pending 路径不得触碰 SkillService.list_skills"
