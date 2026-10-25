"""Wave 核验 — SkillEvolutionService 闭环测试(提案 pending → 批准写回)。"""

import json

import pytest

from neurova.evolution.eval.config import EvolutionConfig
from neurova.evolution.eval.dataset import EvalDataset, EvalExample
from neurova.evolution.eval.service import SkillEvolutionService

# 本档走 `service.evolve`，与同目录 `test_caseLevelRegressionGate` /
# `test_runOutcomeLedgerConsistency` 同一条链路：约束闸的语义相似度面会用到 jieba
# （`constraints.py` 的 `_tokenize`）。字典冷启动本身已在收集期一次建完
# （`tests/conftest.py` 的 `pytest_configure` → `knowledge.search.warmJieba`），
# 这一行是**父墙**：本档一次跑 8 例 × 若干次评测，正常 2s 级、机器忙时不该被全局 30s
# 掐断在中间。数值与两档兄弟逐字相同，不新造第二种标法。
pytestmark = pytest.mark.timeout(120)


BASELINE = "基础技能正文。" + "补充说明文字用于满足增长闸的基线长度要求。" * 2  # >60 字符


def _ds():
    return EvalDataset(
        train=[EvalExample(task_input=f"t{i}", expected_behavior="r") for i in range(4)],
        val=[EvalExample(task_input=f"v{i}", expected_behavior="r") for i in range(2)],
        holdout=[EvalExample(task_input=f"h{i}", expected_behavior="r") for i in range(2)],
    )


@pytest.fixture
def svc(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_TEXT_EVOLUTION", "1")
    return SkillEvolutionService("agent-x", base_dir=tmp_path / "evo")


async def _judge(*, task_input, expected_behavior, output, skill_text, **kw):
    from neurova.evolution.eval.fitness import FitnessScore
    c = 0.9 if "IMPROVED" in skill_text else 0.2
    return FitnessScore(correctness=c, procedure_following=c, conciseness=c, feedback="")


async def _mutate(*, artifact_text, artifact_type, failures):
    return artifact_text + "\nIMPROVED"


class _FakeAgent:
    async def run(self, *, skill_text, task_input):
        return skill_text


class TestEvolveFlow:
    @pytest.mark.asyncio
    async def test_disabled_returns_rejected(self, tmp_path, monkeypatch):
        monkeypatch.delenv("NEUROVA_TEXT_EVOLUTION", raising=False)
        monkeypatch.setenv("NEUROVA_EVOLUTION_SETTINGS", str(tmp_path / "settings.json"))
        service = SkillEvolutionService("agent-x", base_dir=tmp_path / "evo")
        result, proposal = await service.evolve(
            skill_id="s1", skill_text="BASE", dataset=_ds(),
            agent=_FakeAgent(),
        )
        assert result.rejected and result.reject_reason == "disabled"
        assert proposal is None

    @pytest.mark.asyncio
    async def test_accept_produces_pending_proposal(self, svc):
        result, proposal = await svc.evolve(
            skill_id="s1", skill_text=BASELINE, dataset=_ds(),
            agent=_FakeAgent(), config=EvolutionConfig(iterations=1, min_improvement=0.0),
            judge=_judge, mutate=_mutate, bench_gate=None,
        )
        assert not result.rejected
        assert proposal is not None and proposal.status == "pending"
        assert proposal.improved_text == BASELINE + "\nIMPROVED"
        assert proposal.holdout_after > proposal.holdout_before
        # 提案落盘且默认列表含 pending
        pending = svc.list_proposals(status="pending")
        assert len(pending) == 1
        assert pending[0]["skill_id"] == "s1"
        # 拒绝的变体不会写技能:approve 前正文仍是基线
        assert result.deployed_text != BASELINE
        assert pending[0]["improved_text"] != pending[0]["baseline_text"]

    @pytest.mark.asyncio
    async def test_proposal_approve_writes_back(self, svc, tmp_path, monkeypatch):
        """批准是唯一变更点:improved_text 写回 config.context_template。"""
        applied = {}

        class _Entry:
            def __init__(self, cfg):
                self._cfg = cfg

        def fake_update_auto_skill(skill_id, version=None, config=None, name=None,
                                   description=None, *, enforce_quality=None, **kwargs):
            applied["config"] = config
            applied["version"] = version
            return True

        proposal = {
            "proposal_id": "evo_test", "agent_id": "agent-x", "skill_id": "s1",
            "artifact_type": "skill", "baseline_text": "BASE",
            "improved_text": "BASE+IMPROVED", "status": "pending",
        }
        (svc._dir).mkdir(parents=True, exist_ok=True)
        (svc._proposals_file).write_text(json.dumps([proposal]), encoding="utf-8")

        import neurova.skills.skill_service as ss_mod

        fake_info = {"id": "s1", "version": "1.0.0",
                     "manifest": {"config": {"context_template": "BASE"}}}
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(ss_mod.SkillService, "get_skill_info", lambda self, sid: fake_info)
            mp.setattr(ss_mod.SkillService, "update_auto_skill",
                       lambda self, sid, version=None, config=None, name=None,
                       description=None, **kw: fake_update_auto_skill(
                           sid, version, config, name, description,
                           enforce_quality=kw.get("enforce_quality")))
            ok = svc.decide("evo_test", approve=True, approver="tester")
        assert ok
        assert applied["config"]["context_template"] == "BASE+IMPROVED"
        assert applied["version"] == "1.0.1"
        # §6-2 阶段①：规范终态是 applied（原子决定），且决策可归因
        assert svc.list_proposals()[0]["status"] == "applied"
        assert svc.list_proposals()[0]["decided_by"] == "tester"

    @pytest.mark.asyncio
    async def test_proposal_reject_keeps_skill(self, svc):
        proposal = {
            "proposal_id": "evo_r", "agent_id": "agent-x", "skill_id": "s1",
            "baseline_text": "BASE", "improved_text": "X", "status": "pending",
        }
        (svc._dir).mkdir(parents=True, exist_ok=True)
        (svc._proposals_file).write_text(json.dumps([proposal]), encoding="utf-8")
        assert svc.decide("evo_r", approve=False)
        assert svc.list_proposals()[0]["status"] == "rejected"

    @pytest.mark.asyncio
    async def test_double_decide_idempotent(self, svc):
        proposal = {
            "proposal_id": "evo_d", "agent_id": "agent-x", "skill_id": "s1",
            "baseline_text": "B", "improved_text": "I", "status": "approved",
        }
        (svc._dir).mkdir(parents=True, exist_ok=True)
        (svc._proposals_file).write_text(json.dumps([proposal]), encoding="utf-8")
        assert not svc.decide("evo_d", approve=True), "已处理提案不得重复决定"

    @pytest.mark.asyncio
    async def test_run_audit_persisted(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NEUROVA_TEXT_EVOLUTION", "1")
        service = SkillEvolutionService("agent-y", base_dir=tmp_path / "evo")
        monkeypatch.setattr(
            "neurova.evolution.eval.runner.SkillEvolutionRunner._call_judge",
            lambda self, **kw: _judge(**kw),
        )
        result, proposal = await service.evolve(
            skill_id="s1", skill_text=BASELINE, dataset=_ds(),
            agent=_FakeAgent(), config=EvolutionConfig(iterations=1, min_improvement=0.0),
            judge=_judge, mutate=_mutate, bench_gate=None,
        )
        runs = list((tmp_path / "evo" / "runs").glob("run_*.json"))
        assert runs, "每次进化运行必须落审计文件"
        payload = json.loads(runs[0].read_text(encoding="utf-8"))
        assert payload["skill_id"] == "s1"
        assert "holdout_before" in payload

    @pytest.mark.asyncio
    async def test_runAuditIsLinkedToItsProposal(self, tmp_path, monkeypatch):
        """§6-95 后半：审计文件要有读者——提案记录带着 `run_id` 指回它（台账原话"只写不读"）。

        取的是**现有提案详情面**这条既有的读路径，不新建端点：提案 = 审批人已经在看的
        东西，运行 = 它是凭什么分数出来的。落盘侧不写关联键，读侧就永远只能靠文件名猜。
        """
        monkeypatch.setenv("NEUROVA_TEXT_EVOLUTION", "1")
        service = SkillEvolutionService("agent-link", base_dir=tmp_path / "evo")
        monkeypatch.setattr(
            "neurova.evolution.eval.runner.SkillEvolutionRunner._call_judge",
            lambda self, **kw: _judge(**kw),
        )
        result, proposal = await service.evolve(
            skill_id="s1", skill_text=BASELINE, dataset=_ds(),
            agent=_FakeAgent(), judge=_judge, mutate=_mutate, bench_gate=None,
            config=EvolutionConfig(iterations=1, min_improvement=0.0),
        )
        assert proposal is not None, result.reject_reason
        runId = proposal.to_dict()["run_id"]
        assert runId, "提案没带 run_id ⇒ 详情面取不到运行，审计文件仍是只写不读"
        onDisk = json.loads(
            (tmp_path / "evo" / "runs" / f"{runId}.json").read_text(encoding="utf-8"))
        assert onDisk["run_id"] == runId, "文件名与文件内的 run_id 两份口径会漂移"
        assert service.readRun(runId) == onDisk, "读侧取回的内容与落盘不一致"
        # 详情面（前端 `EvolutionRunAudit`）要读的那几个键，必须由**生产写侧**真的写出来。
        # 用 dataclass 字段名去造夹具会假绿：线上名是 `holdout_cases`，字段名才是
        # `holdout_case_scores`——按字段名写死断言，面板读一个不存在的键也不会红。
        assert {"at", "run_id", "holdout_cases", "judge_available"} <= set(onDisk), sorted(onDisk)

    @pytest.mark.asyncio
    async def test_readRunRefusesForeignPaths(self, tmp_path, monkeypatch):
        """读侧只认自己那批文件名——`run_id` 来自磁盘上的记录，不能当路径拼。"""
        monkeypatch.setenv("NEUROVA_TEXT_EVOLUTION", "1")
        service = SkillEvolutionService("agent-safe", base_dir=tmp_path / "evo")
        (tmp_path / "evo" / "runs").mkdir(parents=True)
        (tmp_path / "evo" / "secret.json").write_text('{"leak": true}', encoding="utf-8")
        for foreign in ("", "../secret", "run_../secret", "/etc/passwd",
                        "run_x/../../secret", "secret.json"):
            assert service.readRun(foreign) is None, f"`{foreign}` 竟被读成运行记录"
        assert service.readRun(None) is None, "None 必须按读不到处理，而不是抛"

    @pytest.mark.asyncio
    async def test_readRunDistinguishesMissingFileFromEmptyId(self, tmp_path, monkeypatch):
        """"这条运行记录不见了"与"这一轮根本没落运行"是两件事，读侧不得混成一个 None 了事。

        混成一件事时，端点只能二选一：要么谎报"没有运行"，要么静默省略——两种都把
        审计面的缺失洗成"看起来正常"（教义第 2 条禁止的降级形态）。
        """
        monkeypatch.setenv("NEUROVA_TEXT_EVOLUTION", "1")
        service = SkillEvolutionService("agent-state", base_dir=tmp_path / "evo")
        assert service.runLookup("")[0] == "none_recorded"
        assert service.runLookup("run_20260101T000000_abc123")[0] == "missing"
        (tmp_path / "evo" / "runs").mkdir(parents=True)
        (tmp_path / "evo" / "runs" / "run_20260101T000000_abc123.json").write_text(
            '{"run_id": "run_20260101T000000_abc123"}', encoding="utf-8")
        state, payload = service.runLookup("run_20260101T000000_abc123")
        assert state == "attached" and payload["run_id"] == "run_20260101T000000_abc123"

