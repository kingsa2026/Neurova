"""Wave 核验 — 文本进化 API 面(鉴权口径:读=登录,写=admin)。"""

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tests.route_table import registeredPaths

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


def _pending_proposal(svc_dir, pid="evo_x1", extra=None):
    record = {
        "proposal_id": pid, "agent_id": "a1", "skill_id": "s1",
        "artifact_type": "template", "baseline_text": "B", "improved_text": "I",
        "status": "pending", "holdout_before": 0.2, "holdout_after": 0.9,
        "iterations_run": 1, "created_at": "", "decided_at": "",
    }
    record.update(extra or {})
    (svc_dir / "proposals.json").write_text(
        json.dumps([record]), encoding="utf-8",
    )


def _pointServiceAt(monkeypatch, target):
    """把服务门面钉到 tmp 目录（与 `test_list_and_detail` 同一形态，收成一处）。"""
    from neurova.evolution.eval import service as svc_mod

    monkeypatch.setattr(svc_mod.SkillEvolutionService, "__init__",
                        lambda self, agent_id, base_dir=None: setattr(
                            self, "_dir", target) or setattr(
                            self, "_proposals_file", target / "proposals.json"))


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
        target = tmp_path / "evo"
        target.mkdir()
        _pending_proposal(target, extra={
            "requires_manual_review": True, "judge_fallback": "deterministic",
        })
        _pointServiceAt(monkeypatch, target)
        lst = client.get(f"{BASE}/skills/a1/proposals", params={"status": "pending"}).json()["data"]
        assert len(lst) == 1
        assert "baseline_text" not in lst[0]  # 列表不夹带正文
        # judge 回退提案的人工复核标记必须随列表出街（技能页据此挂标签）。
        assert lst[0]["requires_manual_review"] is True
        assert lst[0]["judge_fallback"] == "deterministic"
        detail = client.get(f"{BASE}/skills/a1/proposals/evo_x1").json()["data"]
        assert detail["improved_text"] == "I"

    def test_detailAttachesTheAuditRun(self, client, tmp_path, monkeypatch):
        """§6-95 后半：提案详情面把那次进化的审计运行读出来（runs/*.json 从此有读者）。

        判据打在**外部可观察响应**上而不是"文件确实存在"：审批人看到的是这条提案凭什么
        例级读数与判分可用性出街——那半份事实此前只在盘上，无人取。
        """
        target = tmp_path / "evo"
        (target / "runs").mkdir(parents=True)
        runId = "run_20261010T040000_abc123"
        (target / "runs" / f"{runId}.json").write_text(json.dumps({
            "run_id": runId, "skill_id": "s1", "artifact_type": "template",
            "holdout_before": 0.2, "holdout_after": 0.9,
            # 线上键名来自 `EvolutionRunResult.to_dict()`（`holdout_cases`），
            # 不是 dataclass 的字段名 `holdout_case_scores` —— 拿字段名造夹具会让
            # 这条判据假绿：详情面读着一个不存在的键，测试却照样通过。
            "holdout_cases": {"t1": {"baseline": 0.1, "candidate": 0.9}},
            "judge_available": True,
        }), encoding="utf-8")
        _pending_proposal(target, extra={"run_id": runId})
        _pointServiceAt(monkeypatch, target)

        data = client.get(f"{BASE}/skills/a1/proposals/evo_x1").json()["data"]
        assert data["evolution_run_status"] == "attached", data
        assert data["evolution_run"]["holdout_cases"]["t1"]["candidate"] == 0.9
        # 列表面不夹带运行明细（与"列表不夹带正文"同一口径）
        lst = client.get(f"{BASE}/skills/a1/proposals",
                         params={"status": "pending"}).json()["data"]
        assert "evolution_run" not in lst[0], lst[0]

    def test_detailNamesAMissingAuditRunRatherThanOmittingIt(self, client, tmp_path, monkeypatch):
        """run_id 在、文件不在 ⇒ 必须出声点名，不能静默省略、也不能谎报"没有运行"。"""
        target = tmp_path / "evo"
        target.mkdir()
        _pending_proposal(target, extra={"run_id": "run_20261010T040000_dead01"})
        _pointServiceAt(monkeypatch, target)

        data = client.get(f"{BASE}/skills/a1/proposals/evo_x1").json()["data"]
        assert data["evolution_run"] is None, data
        assert data["evolution_run_status"] == "missing", data

    def test_detailOnLegacyProposalWithoutRunKeySaysNoneRecorded(
            self, client, tmp_path, monkeypatch):
        """旧记录没有 run_id 这一键（改动之前落盘的提案）⇒ 读侧按"当轮未记"报，不得抛。"""
        target = tmp_path / "evo"
        target.mkdir()
        _pending_proposal(target)  # 不塞 run_id，等价于历史提案
        _pointServiceAt(monkeypatch, target)

        data = client.get(f"{BASE}/skills/a1/proposals/evo_x1").json()["data"]
        assert data["evolution_run"] is None, data
        assert data["evolution_run_status"] == "none_recorded", data

    def test_approve_and_reject_call_decide(self, client, monkeypatch):
        from neurova.evolution.eval import service as svc_mod

        calls = []
        monkeypatch.setattr(svc_mod.SkillEvolutionService, "__init__",
                            lambda self, agent_id, base_dir=None: None)
        # §6-2 阶段①：decide 带审批人归因（approve 缺审批人 = 400）
        monkeypatch.setattr(svc_mod.SkillEvolutionService, "decide",
                            lambda self, pid, approve, registry=None, approver="": calls.append((pid, approve)) or True)
        assert client.post(f"{BASE}/skills/a1/proposals/evo_x1/approve").status_code == 200
        assert client.post(f"{BASE}/skills/a1/proposals/evo_x1/reject").status_code == 200
        assert calls == [("evo_x1", True), ("evo_x1", False)]

    def test_approve_missing_404(self, client, monkeypatch):
        from neurova.evolution.eval import service as svc_mod

        monkeypatch.setattr(svc_mod.SkillEvolutionService, "__init__",
                            lambda self, agent_id, base_dir=None: None)
        monkeypatch.setattr(svc_mod.SkillEvolutionService, "decide",
                            lambda self, pid, approve, registry=None, approver="": False)
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
        routes = set(registeredPaths(client.app))
        assert f"{BASE}/settings" in routes
        assert f"{BASE}/skills/{{agent_id}}/evolve" in routes
