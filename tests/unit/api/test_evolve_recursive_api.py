# -*- coding: utf-8 -*-
"""R5 递归多轮演化 API（POST /skills/{agent_id}/evolve-recursive）。

镜像既有 /evolve 端点的守卫形态：未知技能 404、空正文 422、epochs 合法域
1–10、预算闸按「单轮计划 × epochs」放大；service.evolveRecursive 的报告
随响应返回（proposal 转 dict）。
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.endpoints import text_evolution_api as api
from neurova.api.deps import get_current_user
from tests.route_table import registeredPaths

BASE = "/api/v1/text-evolution"
USER = {"user_id": "u1", "username": "u1", "role": "admin"}
ADMIN = USER


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_EVOLUTION_SETTINGS", str(tmp_path / "settings.json"))
    app = FastAPI()
    app.include_router(api.router, prefix=BASE)
    with TestClient(app, raise_server_exceptions=False) as c:
        c.app.dependency_overrides[get_current_user] = lambda: USER
        c.app.dependency_overrides[api._admin_dep] = lambda: ADMIN
        yield c


def _stubSkillInfo(monkeypatch, info):
    import neurova.skills.skill_service as ss

    monkeypatch.setattr(ss.SkillService, "__init__", lambda self, **kw: None)
    monkeypatch.setattr(ss.SkillService, "get_skill_info", lambda self, sid: info)


def _stubRecursive(monkeypatch, report):
    from neurova.evolution.eval import service as svc_mod

    async def fake(self, **kw):
        return report

    monkeypatch.setattr(svc_mod.SkillEvolutionService, "evolveRecursive", fake)


def _stubDataset(monkeypatch):
    """离线目录里 build_dataset 三级回退取不到用例——钉成固定评测集。"""
    from neurova.evolution.eval import service as svc_mod
    from neurova.evolution.eval.dataset import EvalDataset, EvalExample

    ds = EvalDataset(
        train=[EvalExample(task_input=f"t{i}", expected_behavior="要点") for i in range(4)],
        val=[EvalExample(task_input=f"v{i}", expected_behavior="要点") for i in range(2)],
        holdout=[EvalExample(task_input=f"h{i}", expected_behavior="要点") for i in range(2)],
    )

    async def fake_build(self, skill_id, skill_text, source="auto"):
        return ds

    monkeypatch.setattr(svc_mod.SkillEvolutionService, "build_dataset", fake_build)


def _report(**over):
    base = {
        "skill_id": "s1", "baseline_text": "B", "deployed_text": "B1",
        "epochs_run": 2, "epochs": [{"epoch": 1}, {"epoch": 2}],
        "total_improvement": 0.04, "stopped_reason": "epochs_exhausted",
        "proposal": None,
    }
    base.update(over)
    return base


INFO = {"id": "s1", "description": "d", "manifest": {"config": {"context_template": "B"}}}


class TestEvolveRecursiveEndpoint:
    def test_route_registered(self, client):
        assert f"{BASE}/skills/{{agent_id}}/evolve-recursive" in registeredPaths(client.app)

    def test_unknown_skill_404(self, client, monkeypatch):
        _stubSkillInfo(monkeypatch, None)
        r = client.post(f"{BASE}/skills/a1/evolve-recursive", json={"skill_id": "ghost"})
        assert r.status_code == 404

    def test_empty_text_422(self, client, monkeypatch):
        _stubSkillInfo(monkeypatch, {"id": "s1", "description": "", "manifest": {}})
        r = client.post(f"{BASE}/skills/a1/evolve-recursive", json={"skill_id": "s1"})
        assert r.status_code == 422

    def test_epochs_domain_validated(self, client, monkeypatch):
        _stubSkillInfo(monkeypatch, INFO)
        assert client.post(f"{BASE}/skills/a1/evolve-recursive",
                           json={"skill_id": "s1", "epochs": 0}).status_code == 422
        assert client.post(f"{BASE}/skills/a1/evolve-recursive",
                           json={"skill_id": "s1", "epochs": 11}).status_code == 422

    def test_report_returned_with_proposal_dict(self, client, monkeypatch):
        _stubSkillInfo(monkeypatch, INFO)
        _stubDataset(monkeypatch)
        report = _report(proposal=_FakeProposal())
        _stubRecursive(monkeypatch, report)
        r = client.post(f"{BASE}/skills/a1/evolve-recursive",
                        json={"skill_id": "s1", "epochs": 2})
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["epochs_run"] == 2
        assert data["stopped_reason"] == "epochs_exhausted"
        assert data["proposal"]["proposal_id"] == "evo_x9"

    def test_service_receives_epochs_and_iterations(self, client, monkeypatch):
        _stubSkillInfo(monkeypatch, INFO)
        _stubDataset(monkeypatch)
        seen: dict = {}

        async def fake(self, **kw):
            seen.update(kw)
            return _report()

        from neurova.evolution.eval import service as svc_mod

        monkeypatch.setattr(svc_mod.SkillEvolutionService, "evolveRecursive", fake)
        client.post(f"{BASE}/skills/a1/evolve-recursive",
                    json={"skill_id": "s1", "epochs": 3, "iterations": 2})
        assert seen["epochs"] == 3
        assert seen["iterations"] == 2


class _FakeProposal:
    def to_dict(self):
        return {"proposal_id": "evo_x9"}
