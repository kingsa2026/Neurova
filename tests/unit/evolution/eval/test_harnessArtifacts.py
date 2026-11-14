# -*- coding: utf-8 -*-
"""V5 Pareto 可部署工件打包 —— 红灯测试。

对照档：docs/08-research/videoevolve_vs_neurova_harness_evolution_comparison_2026-11-14.md §3-V5。
论文（arXiv 2610.01766）：开发期搜索结束，**部署的是固定 harness**——冠军与
非劣变体是可交付物。HarnessPro 对照档登记的残差（N5 工件化）：本仓的
pareto_variants 此前只是结果面读数＋adopt-variant 单点采纳，没有版本化工件。

本文件钉：
1. ArtifactStore：save/get/list/patch + 外来 id 拒读（与 run 审计同款路径纪律）；
2. buildArtifact：冠军＋非劣变体＋证据指针（run/proposal/journal commit）＋
   成本指纹＋面读数，状态 pending；
3. evolve 产出提案时同步落工件；decide 批准后工件转 applied 并回填 journal commit；
4. rollback：按工件把技能正文恢复到基线（无漂移才可回滚；漂移如实拒绝）；
5. API：list / detail / rollback 三端点。
"""

import json

import pytest
from fastapi.testclient import TestClient

from neurova.evolution.eval.artifacts import ArtifactStore, buildArtifact
from neurova.evolution.eval.config import EvolutionConfig
from neurova.evolution.eval.dataset import EvalDataset, EvalExample
from neurova.evolution.eval.service import SkillEvolutionService

pytestmark = pytest.mark.timeout(120)

BASELINE = "基础技能正文。" + "补充说明文字用于满足增长闸的基线长度要求。" * 2
IMPROVED = BASELINE + "\nIMPROVED"


def _ds():
    return EvalDataset(
        train=[EvalExample(task_input=f"t{i}", expected_behavior="r") for i in range(4)],
        val=[EvalExample(task_input=f"v{i}", expected_behavior="r") for i in range(2)],
        holdout=[EvalExample(task_input=f"h{i}", expected_behavior="r") for i in range(2)],
    )


async def _judge(*, task_input, expected_behavior, output, skill_text, **kw):
    from neurova.evolution.eval.fitness import FitnessScore

    c = 0.9 if "IMPROVED" in skill_text else 0.2
    return FitnessScore(correctness=c, procedure_following=c, conciseness=c, feedback="")


async def _mutate(*, artifact_text, artifact_type, failures, **kw):
    return artifact_text + "\nIMPROVED"


class _FakeAgent:
    async def run(self, *, skill_text, task_input):
        return skill_text


def _cfg():
    return EvolutionConfig(iterations=1, min_improvement=0.0, noise_repeats=1,
                           exec_suite_enabled=False, anchor_floor_enabled=False,
                           heldout_ratio=0.0)


class TestArtifactStore:
    def test_save_get_roundtrip(self, tmp_path):
        store = ArtifactStore(tmp_path / "artifacts")
        artifact = {"skill_id": "s1", "status": "pending"}
        artifact_id = store.save(artifact)
        assert artifact_id.startswith("art_")
        loaded = store.get(artifact_id)
        assert loaded["skill_id"] == "s1"
        assert loaded["artifact_id"] == artifact_id

    def test_list_filters_by_skill(self, tmp_path):
        store = ArtifactStore(tmp_path / "artifacts")
        a1 = store.save({"skill_id": "s1"})
        store.save({"skill_id": "s2"})
        ids = [a["artifact_id"] for a in store.list(skill_id="s1")]
        assert ids == [a1]

    def test_patch_updates_fields(self, tmp_path):
        store = ArtifactStore(tmp_path / "artifacts")
        artifact_id = store.save({"skill_id": "s1", "status": "pending"})
        assert store.patch(artifact_id, {"status": "applied"}) is True
        assert store.get(artifact_id)["status"] == "applied"

    def test_foreign_ids_refused(self, tmp_path):
        """id 来自落盘记录，不能当路径拼（与 run 审计读侧同款纪律）。"""
        store = ArtifactStore(tmp_path / "artifacts")
        (tmp_path / "artifacts").mkdir(parents=True)
        (tmp_path / "artifacts" / "secret.json").write_text('{"leak": true}',
                                                           encoding="utf-8")
        for foreign in ("", "../secret", "art_../secret", "/etc/passwd",
                        "art_x/../../secret", "secret.json", None):
            assert store.get(foreign) is None, f"`{foreign}` 竟被读成工件"

    def test_get_missing_is_none_not_raise(self, tmp_path):
        store = ArtifactStore(tmp_path / "artifacts")
        assert store.get("art_20990101T000000_abc123") is None


class TestBuildArtifact:
    def test_shape_carries_champion_variants_evidence(self):
        result = type("R", (), {})()
        result.pareto_variants = [
            {"text": "V1", "score": 0.9, "tier": "lite", "cost_usd": 0.1, "tokens": 10}]
        result.holdout_before = 0.5
        result.holdout_after = 0.8
        result.heldout_before = 0.0
        result.heldout_after = 0.0
        result.heldout_improvement = 0.0
        proposal = {"proposal_id": "evo_x", "run_id": "run_1",
                    "improved_text": IMPROVED, "baseline_text": BASELINE,
                    "experiment_fingerprint": "fp1",
                    "deployment_cost": {"state": "unmeasured"}}
        artifact = buildArtifact(
            skill_id="s1", artifact_type="template", proposal=proposal,
            result=result, config=_cfg())

        assert artifact["status"] == "pending"
        assert artifact["skill_id"] == "s1"
        assert artifact["champion_text"] == IMPROVED
        assert artifact["baseline_text"] == BASELINE
        assert artifact["variants"] == result.pareto_variants
        assert artifact["evidence"]["proposal_id"] == "evo_x"
        assert artifact["evidence"]["run_id"] == "run_1"
        assert artifact["evidence"]["journal_commit"] is None
        assert artifact["scores"]["holdout_after"] == 0.8
        assert artifact["surface"]["name"] == "template"
        assert artifact["cost"] == {"state": "unmeasured"}
        assert artifact["experiment_fingerprint"] == "fp1"


class TestServiceArtifactLoop:
    @pytest.mark.asyncio
    async def test_evolve_produces_pending_artifact(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NEUROVA_TEXT_EVOLUTION", "1")
        svc = SkillEvolutionService("art-agent", base_dir=tmp_path / "evo")
        result, proposal = await svc.evolve(
            skill_id="s1", skill_text=BASELINE, dataset=_ds(),
            agent=_FakeAgent(), judge=_judge, mutate=_mutate, config=_cfg())

        assert proposal is not None, result.reject_reason
        artifacts = svc.artifactStore.list(skill_id="s1")
        assert len(artifacts) == 1, "过门提案必须伴随一份可部署工件"
        artifact = artifacts[0]
        assert artifact["status"] == "pending"
        assert artifact["champion_text"] == proposal.improved_text
        assert artifact["evidence"]["proposal_id"] == proposal.proposal_id
        assert artifact["evidence"]["run_id"] == proposal.run_id

    @pytest.mark.asyncio
    async def test_approve_marks_artifact_applied(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NEUROVA_TEXT_EVOLUTION", "1")
        svc = SkillEvolutionService("art-agent", base_dir=tmp_path / "evo")
        _result, proposal = await svc.evolve(
            skill_id="s1", skill_text=BASELINE, dataset=_ds(),
            agent=_FakeAgent(), judge=_judge, mutate=_mutate, config=_cfg())

        import neurova.skills.skill_service as ss_mod

        fake_info = {"id": "s1", "version": "1.0.0",
                     "manifest": {"config": {"context_template": BASELINE}}}
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(ss_mod.SkillService, "get_skill_info",
                       lambda self, sid: dict(fake_info))
            mp.setattr(ss_mod.SkillService, "update_auto_skill",
                       lambda self, sid, **kw: True)
            assert svc.decide(proposal.proposal_id, approve=True, approver="tester")

        artifact = svc.artifactStore.list(skill_id="s1")[0]
        assert artifact["status"] == "applied"

    @pytest.mark.asyncio
    async def test_rollback_restores_baseline(self, tmp_path, monkeypatch):
        """按工件回滚：把技能正文恢复到该工件记录的基线（批准的逆操作）。"""
        monkeypatch.setenv("NEUROVA_TEXT_EVOLUTION", "1")
        svc = SkillEvolutionService("art-agent", base_dir=tmp_path / "evo")
        _result, proposal = await svc.evolve(
            skill_id="s1", skill_text=BASELINE, dataset=_ds(),
            agent=_FakeAgent(), judge=_judge, mutate=_mutate, config=_cfg())

        applied = {}
        import neurova.skills.skill_service as ss_mod

        fake_info = {"id": "s1", "version": "1.0.0",
                     "manifest": {"config": {"context_template": BASELINE}}}

        def fake_update(skill_id, version=None, config=None, **kw):
            applied["config"] = config
            fake_info["manifest"]["config"] = config  # 应用后「当前正文」变成冠军
            return True

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(ss_mod.SkillService, "get_skill_info",
                       lambda self, sid: dict(fake_info))
            mp.setattr(ss_mod.SkillService, "update_auto_skill",
                       lambda self, sid, **kw: fake_update(sid, **kw))
            assert svc.decide(proposal.proposal_id, approve=True, approver="tester")
            assert applied["config"]["context_template"] == IMPROVED

            readout = svc.rollbackArtifact(
                svc.artifactStore.list(skill_id="s1")[0]["artifact_id"])

        assert readout["rolled_back"] is True
        assert applied["config"]["context_template"] == BASELINE, "回滚必须恢复基线正文"
        artifact = svc.artifactStore.list(skill_id="s1")[0]
        assert artifact["status"] == "rolled_back"

    @pytest.mark.asyncio
    async def test_rollback_refuses_when_skill_drifted(self, tmp_path, monkeypatch):
        """技能正文已不是工件冠军形态（人工改过/换了代）⇒ 拒绝回滚，不覆盖。"""
        monkeypatch.setenv("NEUROVA_TEXT_EVOLUTION", "1")
        svc = SkillEvolutionService("art-agent", base_dir=tmp_path / "evo")
        _result, proposal = await svc.evolve(
            skill_id="s1", skill_text=BASELINE, dataset=_ds(),
            agent=_FakeAgent(), judge=_judge, mutate=_mutate, config=_cfg())

        import neurova.skills.skill_service as ss_mod

        fake_info = {"id": "s1", "version": "1.0.0",
                     "manifest": {"config": {"context_template": BASELINE}}}
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(ss_mod.SkillService, "get_skill_info",
                       lambda self, sid: dict(fake_info))
            mp.setattr(ss_mod.SkillService, "update_auto_skill",
                       lambda self, sid, **kw: True)
            assert svc.decide(proposal.proposal_id, approve=True, approver="tester")

        # 批准后有人把正文改成了别的样子（漂移）
        fake_info["manifest"]["config"]["context_template"] = "人工改过的正文"
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(ss_mod.SkillService, "get_skill_info",
                       lambda self, sid: dict(fake_info))
            with pytest.raises(ValueError):
                svc.rollbackArtifact(
                    svc.artifactStore.list(skill_id="s1")[0]["artifact_id"])


class TestArtifactApi:
    @pytest.fixture()
    def client(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NEUROVA_TEXT_EVOLUTION", "1")
        monkeypatch.setenv("NEUROVA_EVOLUTION_SETTINGS", str(tmp_path / "settings.json"))
        from neurova.api.app import create_app

        app = create_app(enable_memory=False, enable_channels=False)
        override = {"user_id": "adm", "username": "adm", "role": "admin"}
        from neurova.api import auth as auth_mod
        from neurova.api.deps import get_current_user

        app.dependency_overrides[get_current_user] = lambda: override
        app.dependency_overrides[auth_mod.get_current_user] = lambda: override
        return TestClient(app), tmp_path, monkeypatch

    @staticmethod
    def _pointServiceAt(monkeypatch, target):
        """把服务门面钉到 tmp 目录（与 test_text_evolution_api 同款形态）。"""
        from neurova.evolution.eval import service as svc_mod

        def _init(self, agent_id, base_dir=None):
            self.agent_id = agent_id
            self._dir = target
            self._proposals_file = target / "proposals.json"
            self._history_ledger = None
            self._skill_journal = None
            self._artifact_store = None

        monkeypatch.setattr(svc_mod.SkillEvolutionService, "__init__", _init)

    def test_list_and_detail(self, client):
        api, tmp_path, monkeypatch = client
        self._pointServiceAt(monkeypatch, tmp_path / "evo")
        svc = SkillEvolutionService("art-api-agent", base_dir=tmp_path / "evo")
        store = svc.artifactStore
        artifact_id = store.save({"skill_id": "s9", "status": "pending",
                                  "champion_text": "X", "baseline_text": "Y",
                                  "evidence": {"proposal_id": "evo_1"}})
        r = api.get("/api/v1/evolution/skills/art-api-agent/artifacts",
                    params={"skill_id": "s9"})
        assert r.status_code == 200
        rows = r.json()["data"]
        assert [row["artifact_id"] for row in rows] == [artifact_id]
        assert "champion_text" not in rows[0], "列表面不夹带正文"
        r = api.get(f"/api/v1/evolution/skills/art-api-agent/artifacts/{artifact_id}")
        assert r.status_code == 200
        assert r.json()["data"]["champion_text"] == "X"
        assert api.get(
            "/api/v1/evolution/skills/art-api-agent/artifacts/art_missing"
        ).status_code == 404

    def test_rollback_endpoint(self, client):
        api, tmp_path, monkeypatch = client
        self._pointServiceAt(monkeypatch, tmp_path / "evo")
        svc = SkillEvolutionService("art-api-agent", base_dir=tmp_path / "evo")
        proposal = {"proposal_id": "evo_rb", "agent_id": "art-api-agent",
                    "skill_id": "s1", "artifact_type": "skill",
                    "baseline_text": BASELINE, "improved_text": IMPROVED,
                    "status": "applied"}
        (svc._dir).mkdir(parents=True, exist_ok=True)
        (svc._proposals_file).write_text(json.dumps([proposal]), encoding="utf-8")
        artifact_id = svc.artifactStore.save({
            "skill_id": "s1", "status": "applied",
            "champion_text": IMPROVED, "baseline_text": BASELINE,
            "evidence": {"proposal_id": "evo_rb", "run_id": "", "journal_commit": None},
            "variants": [], "scores": {}, "surface": {}, "cost": {},
        })

        import neurova.skills.skill_service as ss_mod

        fake_info = {"id": "s1", "version": "1.0.0",
                     "manifest": {"config": {"context_template": IMPROVED}}}
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(ss_mod.SkillService, "get_skill_info",
                       lambda self, sid: dict(fake_info))
            mp.setattr(ss_mod.SkillService, "update_auto_skill",
                       lambda self, sid, **kw: True)
            r = api.post(
                f"/api/v1/evolution/skills/art-api-agent/artifacts/{artifact_id}/rollback")
        assert r.status_code == 200
        assert r.json()["data"]["rolled_back"] is True
        assert svc.artifactStore.get(artifact_id)["status"] == "rolled_back"
