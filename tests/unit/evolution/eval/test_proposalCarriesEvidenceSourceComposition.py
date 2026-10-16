# -*- coding: utf-8 -*-
"""B 批：`EvalExample.source` 接线——提案带"这批验收证据的用例来源构成"。

## 为什么是接线而不是退役（用户裁定甲）

`source` 此前只写不读（AGENTS §2 断点条款：要么接线要么删除）。它**不是** M-D 那对
`difficulty`/`category`：那两样是 LLM 自报、未经校准、无人验证的标签；而 `source` 是
**产出通道的记账**，写侧本来就有真值（`miner.py:197` 取挖掘记录 `m.get("source","history")`、
`synthetic.py:97` 写 `"synthetic"`），缺的只是读的人。接法取最小而可判的一种：
把它折进**验收证据的构成**——审批人看一条提案时，除了分数，还要知道这分数是在
"golden 手工用例"上量的还是在"合成用例"上量的。

## 三条口径（读错就白接）

- 构成只算**判据集**（`evaluation_split(dataset)`，与 runner 的留出终审同一处取数），
  不算整个语料——把 train 里的用例混进来，读数说的是另一件事。
- 旧记录没有这一格 ⇒ 归**未记**，绝不因为 `EvalExample.source` 有 `"synthetic"` 默认值
  就把它们读成"这批是合成的"（那是拿默认值编证据）。
- 未记的词值与基座维度**共用同一处常量**：`"__unrecorded__"` 说的是"这一格没记"这一件
  事实，不属某个维度；两处各写一份就是第二份定义。

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

BASELINE = "基线正文：先复述再作答。" * 4
MARKER = "IMPROVED"


class _Arm:
    async def run(self, *, skill_text: str, task_input: str) -> str:
        return f"out::{task_input}"


class _Judge:
    async def score(self, *, task_input, expected_behavior, output, skill_text, **kw):
        value = 0.9 if MARKER in skill_text else 0.2
        return FitnessScore(correctness=value, procedure_following=value,
                            conciseness=value, feedback="")


async def _mutate(*, artifact_text, artifact_type, failures, **kw):
    return artifact_text + f"\n{MARKER}"


def _ex(name, source):
    return EvalExample(task_input=name, expected_behavior="要点", source=source)


def _dataset(golden=2, history=1, synthetic=1, trainExtra=0):
    """holdout 放"验收证据"，train 可另放几条不同来源的用例（用来判构成算的是哪一批）。"""
    holdout = ([_ex(f"g{i}", "golden") for i in range(golden)]
               + [_ex(f"h{i}", "history") for i in range(history)]
               + [_ex(f"s{i}", "synthetic") for i in range(synthetic)])
    train = list(holdout) + [_ex(f"t{i}", "history") for i in range(trainExtra)]
    return EvalDataset(train=train, val=[], holdout=list(holdout))


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setenv("NEUROVA_TEXT_EVOLUTION", "1")


async def _evolve(tmp_path, dataset, agent_id="src-agent"):
    svc = SkillEvolutionService(agent_id, base_dir=tmp_path / "evo")
    _result, proposal = await svc.evolve(
        skill_id="sk", skill_text=BASELINE, dataset=dataset, iterations=1,
        config=EvolutionConfig(anchor_floor_enabled=False, cost_rule_enabled=False),
        agent=_Arm(), judge=_Judge(), mutate=_mutate)
    return svc, proposal


class TestCompositionIsOverTheJudgedSplit:
    def test_mixCoversExactlyTheEvidenceSetNotTheCorpus(self):
        from neurova.evolution.eval.service import sourceMixOfEvidence

        ds = _dataset(golden=2, history=1, synthetic=1, trainExtra=3)
        mix = sourceMixOfEvidence(ds)
        assert mix == {"golden": 2, "history": 1, "synthetic": 1}, mix
        # train 里多出的 3 条 history 不得混进来：说的是"这批证据"，不是"这个语料"

    def test_emptySplitYieldsEmptyMixNotADefaultSource(self):
        """判据集为空 ⇒ 空构成；兜一个 "synthetic" 进去就是拿默认值编证据。"""
        from neurova.evolution.eval.service import sourceMixOfEvidence

        assert sourceMixOfEvidence(EvalDataset()) == {}


class TestProposalRecordCarriesIt:
    @pytest.mark.asyncio
    async def testEvolvedProposalRecordsTheMix(self, tmp_path, enabled):
        svc, proposal = await _evolve(tmp_path, _dataset(golden=3, history=1, synthetic=0))
        assert proposal is not None, "这条链没出提案，来源构成无处可验"
        stored = svc.list_proposals()[0]
        assert stored.get("source_mix") == {"golden": 3, "history": 1}, stored

    @pytest.mark.asyncio
    async def testVerdictNumbersIgnoreTheMix(self, tmp_path, enabled):
        """蕴涵格：来源只作解释面。同分不同来源 ⇒ 判据数字必须一字不变。"""
        svcA, propA = await _evolve(tmp_path / "a", _dataset(golden=2, history=2), "src-a")
        svcB, propB = await _evolve(tmp_path / "b", _dataset(golden=4, history=0), "src-b")
        a, b = svcA.list_proposals()[0], svcB.list_proposals()[0]
        for field in ("holdout_before", "holdout_after", "iterations_run"):
            assert a[field] == b[field], (field, a[field], b[field])
        assert a["source_mix"] != b["source_mix"], (
            f"两批证据的来源本该不同，读数却没分开：{a['source_mix']} / {b['source_mix']}")


class TestCoverageReadout:
    def testGroupsBySourceAndKeepsUnrecordedProposalsVisible(self, tmp_path):
        from neurova.evolution.eval.service import STATUS_APPLIED, sourceCoverageReadout

        svc = SkillEvolutionService("src-agent2", base_dir=tmp_path / "evo")
        svc._append_proposal(EvolutionProposal(
            proposal_id="evo_new", agent_id="src-agent2", skill_id="sk",
            artifact_type="skill", baseline_text="a", improved_text="b",
            status=STATUS_APPLIED, source_mix={"golden": 2, "synthetic": 1}))
        # 一条改动之前落盘的旧记录：整键缺席
        legacy = EvolutionProposal(
            proposal_id="evo_old", agent_id="src-agent2", skill_id="sk",
            artifact_type="skill", baseline_text="a", improved_text="b")
        row = legacy.to_dict()
        row.pop("source_mix")
        svc._append_proposal(EvolutionProposal(**row))

        coverage = sourceCoverageReadout(svc.list_proposals())
        bySource = coverage["by_source"]
        assert bySource["golden"] == {"proposals": 1, "approved": 1}, bySource
        assert bySource["__unrecorded__"]["proposals"] == 1, (
            f"旧记录被吞掉了：{bySource}")
        assert coverage["unrecorded_key"] == "__unrecorded__"

    def testUnrecordedWordValueIsSharedNotRetyped(self):
        """未记词值只有一处定义：两个维度共用同一个常量，各写一份就会漂成两组。"""
        from neurova.evolution.eval import service as svc

        assert hasattr(svc, "UNRECORDED_GROUP_KEY"), "未记词值应收成一处（维度中立的名字）"
        assert not hasattr(svc, "UNRECORDED_MODEL_KEY"), (
            "旧名还在就是第二份定义：改名要一次改全，包括判据与读侧")
        assert svc.modelCoverageReadout([])["unrecorded_key"] == svc.UNRECORDED_GROUP_KEY
        assert svc.sourceCoverageReadout([])["unrecorded_key"] == svc.UNRECORDED_GROUP_KEY


class TestListEndpointShapeStaysCompatible:
    @pytest.mark.asyncio
    async def testListProjectsMixAndAddsSiblingCoverageWithoutBreakingData(self, monkeypatch):
        from neurova.api.endpoints import text_evolution_api as api
        from neurova.evolution.eval.service import STATUS_APPLIED

        rows = [
            {"proposal_id": "evo_1", "skill_id": "sk", "status": STATUS_APPLIED,
             "holdout_before": 0.2, "holdout_after": 0.8, "iterations_run": 1,
             "created_at": "t", "decided_at": "d", "source_mix": {"golden": 3}},
            {"proposal_id": "evo_2", "skill_id": "sk", "status": "pending",
             "holdout_before": 0.2, "holdout_after": 0.7, "iterations_run": 1,
             "created_at": "t", "decided_at": ""},
        ]
        monkeypatch.setattr(
            "neurova.evolution.eval.service.SkillEvolutionService.list_proposals",
            lambda self, status=None: rows)
        payload = await api.list_evolution_proposals("src-agent3", status=None,
                                                     user={"user_id": "u"})
        # 形状纪律：`data` 是前端已在消费的列表，覆盖读数走同级新键
        assert isinstance(payload["data"], list), payload
        assert payload["data"][0]["source_mix"] == {"golden": 3}, payload["data"][0]
        assert payload["source_coverage"]["by_source"]["golden"]["approved"] == 1
        assert payload["source_coverage"]["by_source"]["__unrecorded__"]["proposals"] == 1
