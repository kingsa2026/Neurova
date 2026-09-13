"""Wave 核验 — 文本进化 API 面(鉴权口径:读=登录,写=admin)。"""

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.deps import get_current_user
from neurova.api.endpoints import text_evolution_api as api

BASE = "/api/v1/evolution"
USER = {"user_id": "u1", "username": "alice", "role": "user", "neuser_id": "u1"}
ADMIN = {"user_id": "u1", "username": "admin", "role": "admin", "neuser_id": "u1"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_EVOLUTION_SETTINGS", str(tmp_path / "settings.json"))
    app = FastAPI()
    app.include_router(api.router, prefix=BASE)
    with TestClient(app, raise_server_exceptions=False) as c:
        c.app.dependency_overrides[get_current_user] = lambda: USER
        c.app.dependency_overrides[api._admin_dep] = lambda: ADMIN
        yield c


def _pending_proposal(svc_dir, pid="evo_x1"):
    (svc_dir / "proposals.json").write_text(
        json.dumps([{
            "proposal_id": pid, "agent_id": "a1", "skill_id": "s1",
            "artifact_type": "template", "baseline_text": "B", "improved_text": "I",
            "status": "pending", "holdout_before": 0.2, "holdout_after": 0.9,
            "iterations_run": 1, "created_at": "", "decided_at": "",
        }]),
        encoding="utf-8",
    )


class TestSettingsEndpoints:
    def test_get_defaults(self, client):
        r = client.get(f"{BASE}/settings")
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["text_evolution"] is False
        assert data["lifecycle_sweep"] is True

    def test_put_updates_persists(self, client):
        r = client.put(f"{BASE}/settings", json={"text_evolution": True,
                                                 "lifecycle_interval_hours": 48})
        assert r.status_code == 200
        assert r.json()["data"]["text_evolution"] is True
        assert client.get(f"{BASE}/settings").json()["data"]["lifecycle_interval_hours"] == 48

    def test_put_rejects_bad_interval(self, client):
        assert client.put(f"{BASE}/settings", json={"lifecycle_interval_hours": 0}).status_code == 422


class TestLifecycleEndpoints:
    def test_usage_summary(self, client, monkeypatch, tmp_path):
        import neurova.skills.skill_service as ss

        def fake_iter(self):
            yield "a-skill", {"usage": {"state": "stale", "use_count": 2,
                                        "pinned": False, "created_by": "agent",
                                        "last_activity_at_ms": 1}}
            yield "hub-skill", {"usage": {}}

        monkeypatch.setattr(ss.SkillService, "iter_skills", fake_iter)
        data = client.get(f"{BASE}/skills/a1/usage").json()["data"]
        assert data["counts"]["stale"] == 1
        assert {s["skill_id"] for s in data["skills"]} == {"a-skill", "hub-skill"}

    def test_sweep_returns_counts(self, client, monkeypatch):
        import neurova.skills.skill_service as ss
        import neurova.evolution.skill_lifecycle as lc

        monkeypatch.setattr(ss.SkillService, "__init__", lambda self, **kw: None)
        seen = {}
        monkeypatch.setattr(lc, "apply_transitions",
                            lambda svc, **kw: seen.update(ok=True) or {"checked": 0, "marked_stale": 0,
                                                                       "archived": 0, "reactivated": 0,
                                                                       "seeded": 0})
        r = client.post(f"{BASE}/skills/a1/sweep")
        assert r.status_code == 200 and seen.get("ok")

    def test_pin_roundtrip(self, client, monkeypatch):
        import neurova.skills.skill_service as ss

        calls = []
        monkeypatch.setattr(ss.SkillService, "__init__", lambda self, **kw: None)
        monkeypatch.setattr(ss.SkillService, "set_skill_pinned",
                            lambda self, sid, pinned: calls.append((sid, pinned)) or True)
        r = client.post(f"{BASE}/skills/a1/s1/pin", json={"pinned": True})
        assert r.status_code == 200
        assert calls == [("s1", True)]

    def test_pin_unknown_skill_404(self, client, monkeypatch):
        import neurova.skills.skill_service as ss

        monkeypatch.setattr(ss.SkillService, "__init__", lambda self, **kw: None)
        monkeypatch.setattr(ss.SkillService, "set_skill_pinned", lambda self, sid, p: False)
        assert client.post(f"{BASE}/skills/a1/ghost/pin", json={"pinned": True}).status_code == 404


class TestProposalEndpoints:
    def test_list_and_detail(self, client, tmp_path, monkeypatch):
        from neurova.evolution.eval import service as svc_mod

        target = tmp_path / "evo"
        target.mkdir()
        _pending_proposal(target)
        monkeypatch.setattr(svc_mod.SkillEvolutionService, "__init__",
                            lambda self, agent_id, base_dir=None: setattr(
                                self, "_dir", target) or setattr(
                                self, "_proposals_file", target / "proposals.json"))
        lst = client.get(f"{BASE}/skills/a1/proposals", params={"status": "pending"}).json()["data"]
        assert len(lst) == 1
        assert "baseline_text" not in lst[0]  # 列表不夹带正文
        detail = client.get(f"{BASE}/skills/a1/proposals/evo_x1").json()["data"]
        assert detail["improved_text"] == "I"

    def test_approve_and_reject_call_decide(self, client, monkeypatch):
        from neurova.evolution.eval import service as svc_mod

        calls = []
        monkeypatch.setattr(svc_mod.SkillEvolutionService, "__init__",
                            lambda self, agent_id, base_dir=None: None)
        monkeypatch.setattr(svc_mod.SkillEvolutionService, "decide",
                            lambda self, pid, approve, registry=None: calls.append((pid, approve)) or True)
        assert client.post(f"{BASE}/skills/a1/proposals/evo_x1/approve").status_code == 200
        assert client.post(f"{BASE}/skills/a1/proposals/evo_x1/reject").status_code == 200
        assert calls == [("evo_x1", True), ("evo_x1", False)]

    def test_approve_missing_404(self, client, monkeypatch):
        from neurova.evolution.eval import service as svc_mod

        monkeypatch.setattr(svc_mod.SkillEvolutionService, "__init__",
                            lambda self, agent_id, base_dir=None: None)
        monkeypatch.setattr(svc_mod.SkillEvolutionService, "decide",
                            lambda self, pid, approve, registry=None: False)
        assert client.post(f"{BASE}/skills/a1/proposals/ghost/approve").status_code == 404

    def test_list_rejects_bad_status(self, client):
        assert client.get(f"{BASE}/skills/a1/proposals", params={"status": "bogus"}).status_code == 422


class TestEvolveEndpointGuards:
    def test_unknown_skill_404(self, client, monkeypatch):
        import neurova.skills.skill_service as ss

        monkeypatch.setattr(ss.SkillService, "__init__", lambda self, **kw: None)
        monkeypatch.setattr(ss.SkillService, "get_skill_info", lambda self, sid: None)
        r = client.post(f"{BASE}/skills/a1/evolve", json={"skill_id": "ghost"})
        assert r.status_code == 404

    def test_empty_text_422(self, client, monkeypatch):
        import neurova.skills.skill_service as ss

        monkeypatch.setattr(ss.SkillService, "__init__", lambda self, **kw: None)
        monkeypatch.setattr(ss.SkillService, "get_skill_info",
                            lambda self, sid: {"id": sid, "description": "", "manifest": {}})
        r = client.post(f"{BASE}/skills/a1/evolve", json={"skill_id": "s1"})
        assert r.status_code == 422

    def test_source_enum_validated(self, client):
        r = client.post(f"{BASE}/skills/a1/evolve", json={"skill_id": "s1",
                                                          "dataset_source": "hack"})
        assert r.status_code == 422


class TestRouteWiring:
    def test_registered_under_evolution_prefix(self, client):
        routes = {r.path for r in client.app.routes}
        assert f"{BASE}/settings" in routes
        assert f"{BASE}/skills/{{agent_id}}/evolve" in routes
