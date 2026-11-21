# -*- coding: utf-8 -*-
"""R2 首批 EvalCase 生产立案判据（recursive-self-evolution-plan R2）。

钉住三件事：
1. 首批立案：soul / constitution / behavior_rules / rules_sections 四类
   模型可见文本各至少有一条已注册 EvalCase（validateCaseFirst 全 covered）；
2. 判据咬合：每条 case 对"退化回答"必须红、对"合格回答"必须绿
   （assertCaseRedGreen 自检——判据恒真的 case 不算立案）；
3. 接入点：文本进化提案应用路径（SkillEvolutionService）在 subject 未被
   任何已注册 case 覆盖时拒绝应用（fail-closed），覆盖后放行。
"""
import json

import pytest

from neurova.benchmark.evolution_cases import (
    CASE_SOURCE,
    CASE_SUITE_ID,
    registerFirstBatch,
    subjectForProposal,
)
from neurova.benchmark.suite_eval import (
    assertCaseRedGreen,
    clearEvalCases,
    listEvalCases,
    validateCaseFirst,
)

FOUR_SUBJECTS = ("soul", "constitution", "behavior_rules", "rules_sections")


@pytest.fixture(autouse=True)
def _firstBatchRegistry():
    """注册表是模块级全局：每例前清空并重装首批 case，保证互不串扰。"""
    clearEvalCases()
    registerFirstBatch()
    yield
    clearEvalCases()


# ── 首批立案覆盖 ───────────────────────────────────────────────────

def testFirstBatchCoversFourSubjects():
    report = validateCaseFirst(list(FOUR_SUBJECTS))
    assert report["missing"] == []
    assert set(report["covered"]) == set(FOUR_SUBJECTS)


def testFirstBatchCasesCarrySourceAndSuite():
    cases = listEvalCases(CASE_SUITE_ID)
    subjects = {case.subject_id for case in cases}
    assert subjects == set(FOUR_SUBJECTS)
    for case in cases:
        assert case.source == CASE_SOURCE
        assert case.source["kind"] in ("issue", "incident", "review")
        assert case.prompt.strip()
        assert callable(case.check)


def testValidateCaseFirstUncoveredSubjectStillReportsMissing():
    report = validateCaseFirst(["soul", "tool:web_search.description"])
    assert report["covered"] == ["soul"]
    assert report["missing"] == ["tool:web_search.description"]


# ── 判据咬合：退化回答红、合格回答绿（确定性、无 LLM） ─────────────

def _casesBySubject():
    return {case.subject_id: case for case in listEvalCases(CASE_SUITE_ID)}


def testSoulCaseBitesRedThenGreen():
    case = _casesBySubject()["soul"]
    # 退化回答：无身份无职责 → 红；合格回答：身份+职责 → 绿
    assertCaseRedGreen(
        case,
        oldAnswerFn=lambda p: "你好！",
        newAnswerFn=lambda p: "我是凯，我的职责是协助你完成日常任务。",
    )


def testConstitutionCaseBitesRedThenGreen():
    case = _casesBySubject()["constitution"]
    assertCaseRedGreen(
        case,
        oldAnswerFn=lambda p: "我会尽力帮您做事。",
        newAnswerFn=lambda p: "我绝不泄露用户隐私；当规则冲突时，安全优先。",
    )


def testBehaviorRulesCaseBitesRedThenGreen():
    case = _casesBySubject()["behavior_rules"]
    assertCaseRedGreen(
        case,
        oldAnswerFn=lambda p: "今天天气不错。",
        newAnswerFn=lambda p: "必须先核对工具名与参数；不要并行写文件。",
    )


def testRulesSectionsCaseBitesRealAssembledText():
    """rules_sections 用真实拼装输出自检：缺段红、全段绿。"""
    from neurova.context.rules_sections import build_all_sections

    case = _casesBySubject()["rules_sections"]
    full = build_all_sections()
    # 退化文本：删掉一段标题 → 红；真实拼装全文 → 绿
    degraded = full.replace("## 记忆写入规则", "## 已删段")
    assertCaseRedGreen(
        case,
        oldAnswerFn=lambda p: degraded,
        newAnswerFn=lambda p: full,
    )


# ── subject 映射（最小映射单源） ───────────────────────────────────

def testSubjectForProposalMapping():
    assert subjectForProposal({"skill_id": "soul"}) == "soul"
    assert subjectForProposal({"skill_id": "constitution"}) == "constitution"
    assert subjectForProposal({"skill_id": "behavior_rules"}) == "behavior_rules"
    assert subjectForProposal({"skill_id": "rules_sections"}) == "rules_sections"
    # 普通技能不在首批覆盖面：无 subject，case-first 门不适用
    assert subjectForProposal({"skill_id": "s1"}) == ""
    assert subjectForProposal({}) == ""
    assert subjectForProposal(None) == ""


# ── 接入点：应用路径 fail-closed ───────────────────────────────────

def _makeService(tmp_path):
    from neurova.evolution.eval.service import SkillEvolutionService

    return SkillEvolutionService("agent-x", base_dir=tmp_path / "evo")


def _writePendingProposal(svc, skillId, proposalId="evo_soul_1"):
    proposal = {
        "proposal_id": proposalId, "agent_id": "agent-x", "skill_id": skillId,
        "artifact_type": "template", "baseline_text": "BASE",
        "improved_text": "BASE+改进", "status": "pending",
    }
    svc._dir.mkdir(parents=True, exist_ok=True)
    svc._proposals_file.write_text(json.dumps([proposal]), encoding="utf-8")


@pytest.fixture
def patchedSkillService(monkeypatch):
    """替身技能服务：记录写回调用，不落真实库。"""
    import neurova.skills.skill_service as ssMod

    applied = {}
    fakeInfo = {"id": "soul", "version": "1.0.0",
                "manifest": {"config": {"context_template": "BASE"}}}

    def fakeGetSkillInfo(self, skillId):
        return dict(fakeInfo, id=skillId)

    def fakeUpdateAutoSkill(self, skillId, version=None, config=None, name=None,
                            description=None, **kwargs):
        applied["skill_id"] = skillId
        applied["version"] = version
        applied["config"] = config
        return True

    monkeypatch.setattr(ssMod.SkillService, "get_skill_info", fakeGetSkillInfo)
    monkeypatch.setattr(ssMod.SkillService, "update_auto_skill", fakeUpdateAutoSkill)
    return applied


def testDecideRejectsUncoveredSubject(tmp_path, patchedSkillService):
    """零立案时，改动 soul 的提案批准被拒（fail-closed），正文不写、提案保持待审。"""
    clearEvalCases()  # 模拟「先 case 后修」未立案状态
    svc = _makeService(tmp_path)
    _writePendingProposal(svc, "soul")

    ok = svc.decide("evo_soul_1", approve=True, approver="tester")

    assert ok is False
    assert "config" not in patchedSkillService  # 技能正文未被写
    assert svc.list_proposals()[0]["status"] == "pending"  # 保持待审，补 case 后可再批


def testDecidePassesWhenSubjectCovered(tmp_path, patchedSkillService):
    """立案后，同一提案批准放行，改进文本写回技能正文。"""
    svc = _makeService(tmp_path)
    _writePendingProposal(svc, "soul")

    ok = svc.decide("evo_soul_1", approve=True, approver="tester")

    assert ok is True
    assert patchedSkillService["config"]["context_template"] == "BASE+改进"
    assert svc.list_proposals()[0]["status"] == "applied"


def testApplyToSkillChokePointGatesDirectly(tmp_path, patchedSkillService):
    """choke point 直测：_apply_to_skill 对未覆盖 subject 拒绝、覆盖后放行。"""
    svc = _makeService(tmp_path)
    proposal = {"proposal_id": "evo_rs_1", "skill_id": "rules_sections",
                "improved_text": "NEW", "baseline_text": "BASE"}

    clearEvalCases()
    assert svc._apply_to_skill(proposal, None) is False
    assert "config" not in patchedSkillService

    registerFirstBatch()
    assert svc._apply_to_skill(proposal, None) is True
    assert patchedSkillService["config"]["context_template"] == "NEW"
