# -*- coding: utf-8 -*-
"""M-C：评测结果的「被测基座」维度**只出读数、不参与判定**。

## 根因（实测形态，不是"论文有所以我缺"）

`neurova/evolution/` 内 `model_name|model_id` **零命中**；`eval/fitness.py:129` 与
`eval/mutator.py:122` 用的是 `config.judge_model` / `config.optimizer_model`——那是**打分与
生成候选**用的模型，不是**被执行**的模型（默认装配的执行器甚至就是
`SimulatedAgent(model=cfg.judge_model)`，即"判分的模型顺手当了被执行的模型"）。
而本仓基座是管理员运行时可换的配置：一条技能正文在模型 A 下被验收过、切到 B 之后，
仓里没有任何读数说明这件事发生过——审批人看到的 `holdout_after` / `executor_kind`
都不绑定基座。

对照论文的形态是"演化后的 harness 在不同基座上复测迁移"。按用户裁定的档位：
**只出读数、不进判据**，读数稳几轮后再谈进判（先例 `task_yardstick.py` 的"并列呈报、
不参与 gain 判定"）。

## 读数口径（三处不许含糊）

- 模型值由**真正拿去执行的那个对象**推导（与既有 `executor_kind` 同一条纪律），不许手工传。
- 模拟臂没指名模型 ⇒ `client_default`（事实是"交给多模型客户端按路由选"），不猜型号。
- 真轨迹臂的模型选择发生在请求期、执行器自己不持模型 ⇒ `agent_routed`，不编一个名字冒充证据。
- 取不到 ⇒ 空串（未记），绝不兜成某个默认名；分组读数里未记**自成一组**，不许消失。

## 判据八格

A–D resolver 的四种形状；E `ab_compare` 的**两条**返回路径都带（空集那条也得带——
"没跑成"不许读成"没这维度"）；F 提案记录 + 列表端点投影出得去；G 按基座的覆盖读数；
H **不判**：换个基座值，两臂分数与 delta 一字不变，且 runner 判定链里零引用。
"""
from __future__ import annotations

import pytest

from neurova.evolution.eval.config import EvolutionConfig
from neurova.evolution.eval.dataset import EvalDataset, EvalExample
from neurova.evolution.eval.fitness import FitnessScore
from neurova.evolution.eval.service import (
    EvolutionProposal,
    SkillEvolutionService,
)

BASELINE = "基线正文：先复述再作答。"
CANDIDATE = "候选正文：只给代码。"


class _SimArmExecutor:
    """模拟臂形状：runner 按 `run(*, skill_text, task_input)` 调用，自己带 model 字段。"""

    def __init__(self, model: str):
        self.model = model
        self.turns = 0

    async def run(self, *, skill_text: str, task_input: str) -> str:
        self.turns += 1
        return f"out::{task_input}"


class _RealAgentStub:
    async def chat(self, user_input, **kwargs):
        return {"text": f"out::{user_input}", "audio_path": None, "audio_data": None}


def _dataset(withSplit: bool = True) -> EvalDataset:
    items = [EvalExample(task_input=f"t{i}", expected_behavior="要点") for i in range(2)]
    if not withSplit:
        return EvalDataset(train=[], val=[], holdout=[], heldout=[])
    return EvalDataset(train=list(items), val=[], holdout=list(items), heldout=list(items))


def _judgeKeyedByBody():
    async def judge(*, task_input, expected_behavior, output, skill_text, **kw):
        value = 0.9 if skill_text == CANDIDATE else 0.2
        return FitnessScore(correctness=value, procedure_following=value,
                            conciseness=value, feedback="")

    return judge


class TestResolverDerivesFromTheExecutor:

    def _resolve(self, executor):
        from neurova.evolution.eval.service import resolveModelUnderTest

        return resolveModelUnderTest(executor)
    def test_A_explicitModelOnSimulatedArm(self):
        assert self._resolve(_SimArmExecutor("glm-4.6")) == "glm-4.6"

    def test_B_emptyModelIsTaggedAsClientDefaultNotGuessed(self):
        assert self._resolve(_SimArmExecutor("")) == "client_default", (
            "没指名模型时应如实标 client_default，不许挑一个型号冒充绑定过基座的证据"
        )

    def test_C_realTrajectoryArmReportsRoutingNotAFabricatedName(self):
        from neurova.evolution.eval.ab_library import TextArmAgentExecutor

        executor = TextArmAgentExecutor(_RealAgentStub(), skill_name="mc-skill")
        assert self._resolve(executor) == "agent_routed", (
            "真轨迹臂的模型在请求期由 agent 选，读数不许冒充某个具体型号"
        )

    def test_D_unresolvableIsBlank(self):
        assert self._resolve(None) == ""
        assert self._resolve(object()) == ""


class TestReadoutTravelsAndDoesNotGate:
    @pytest.mark.asyncio
    async def test_E_abCompareCarriesItOnBothReturnPaths(self, tmp_path):
        svc = SkillEvolutionService("mc-agent", base_dir=tmp_path / "evo")
        for splitExists, label in ((True, "有对跑"), (False, "空集")):
            report = await svc.ab_compare(
                baseline_text=BASELINE, candidate_text=CANDIDATE,
                dataset=_dataset(splitExists), config=EvolutionConfig(),
                agent=_SimArmExecutor("minimax-2.5"), judge=_judgeKeyedByBody(),
            )
            assert report.get("model_under_test") == "minimax-2.5", (
                f"{label}那条返回路径没带基座读数"
            )
            assert "executor_kind" in report, f"{label}丢了既有的执行面 honesty 格"

    def test_F_proposalRecordCarriesTheField(self, tmp_path):
        svc = SkillEvolutionService("mc-agent2", base_dir=tmp_path / "evo")
        svc._append_proposal(EvolutionProposal(
            proposal_id="evo_f1", agent_id="mc-agent2", skill_id="sk",
            artifact_type="skill", baseline_text="a", improved_text="b",
            model_under_test="deepseek-v4-flash",
        ))
        listed = svc.list_proposals()
        assert listed[0].get("model_under_test") == "deepseek-v4-flash", "提案记录没带出这一格"

    @pytest.mark.asyncio
    async def test_g_listEndpointProjectsItAndCoverage(self, tmp_path, monkeypatch):
        from neurova.api.endpoints import text_evolution_api

        from neurova.evolution.eval.service import STATUS_APPLIED

        rows = [{"proposal_id": "evo_g1", "skill_id": "sk", "status": STATUS_APPLIED,
                 "holdout_before": 0.2, "holdout_after": 0.8, "iterations_run": 1,
                 "created_at": "t", "decided_at": "d", "model_under_test": "glm-4.6"},
                {"proposal_id": "evo_g2", "skill_id": "sk", "status": "pending",
                 "holdout_before": 0.2, "holdout_after": 0.7, "iterations_run": 1,
                 "created_at": "t", "decided_at": "", "model_under_test": ""}]
        monkeypatch.setattr(
            "neurova.evolution.eval.service.SkillEvolutionService.list_proposals",
            lambda self, status=None: rows,
        )
        payload = await text_evolution_api.list_evolution_proposals(
            "mc-agent3", status=None, user={"user_id": "u"})

        # 形状纪律：`data` 是前端已在消费的列表，把它改成 dict 就是打破既有契约；
        # 覆盖读数作**同级新增键**，老调用者按原样读 data 不受影响。
        assert isinstance(payload["data"], list), "列表面被改形状会打破前端既有契约"
        assert payload["data"][0]["model_under_test"] == "glm-4.6", "列表投影丢了基座格"
        coverage = payload["model_coverage"]["by_model"]
        assert coverage["glm-4.6"]["proposals"] == 1 and coverage["glm-4.6"]["approved"] == 1
        assert coverage["__unrecorded__"]["proposals"] == 1, "未记基座的那条消失了"

    def test_H_coverageGroupsUnrecordedSeparately(self, tmp_path):
        from neurova.evolution.eval.service import STATUS_APPLIED

        svc = SkillEvolutionService("mc-agent4", base_dir=tmp_path / "evo")
        for i, (base, status) in enumerate([("glm-4.6", "approved"), ("glm-4.6", "pending"),
                                            ("", STATUS_APPLIED)]):
            svc._append_proposal(EvolutionProposal(
                proposal_id=f"evo_h{i}", agent_id="mc-agent4", skill_id="sk",
                artifact_type="skill", baseline_text="a", improved_text="b",
                status=status, model_under_test=base,
            ))
        from neurova.evolution.eval.service import modelCoverageReadout

        coverage = modelCoverageReadout(svc.list_proposals())
        assert coverage["by_model"]["glm-4.6"] == {"proposals": 2, "approved": 1}
        assert coverage["by_model"]["__unrecorded__"]["proposals"] == 1

    @pytest.mark.asyncio
    async def test_I_modelValueDoesNotChangeTheVerdictNumbers(self, tmp_path):
        """只出读数不判：换个基座值，两臂分数与 delta 必须一字不变。"""
        svc = SkillEvolutionService("mc-agent5", base_dir=tmp_path / "evo")
        reports = []
        for base in ("glm-4.6", "minimax-2.5"):
            reports.append(await svc.ab_compare(
                baseline_text=BASELINE, candidate_text=CANDIDATE,
                dataset=_dataset(), config=EvolutionConfig(),
                agent=_SimArmExecutor(base), judge=_judgeKeyedByBody(),
            ))
        keys = ("baseline_avg", "candidate_avg", "delta", "n", "task_split")
        assert all(r[k] == reports[0][k] for r in reports for k in keys), (
            f"基座值改变了判据读数：{[{r[k] for r in reports} for k in keys]}"
        )
        assert {r["model_under_test"] for r in reports} == {"glm-4.6", "minimax-2.5"}

    def test_J_runnerAcceptanceChainNeverReadsIt(self):
        """判定链里零引用——这格是**蕴涵**：将来谁把它接进 accept，本判据红并要求改判。"""
        from pathlib import Path

        import neurova.evolution.eval.runner as runnerModule

        text = Path(runnerModule.__file__).read_text(encoding="utf-8")
        assert "model_under_test" not in text, (
            "runner 的判定链里出现了 model_under_test；本批裁定是只出读数不判（§7.1-Q3）"
        )
