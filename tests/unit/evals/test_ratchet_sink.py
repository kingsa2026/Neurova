# -*- coding: utf-8 -*-
"""P3-3 评测棘轮自动化判据（recursive-self-evolution-plan P3-3）。

钉住五件事：
1. 三态契约：`RatchetSink.registerFailureCase` 只返回
   registered / duplicate / rejected（自动通道 fail-soft，不抛异常打断管线）；
2. 裁判件保护：非白名单判据模板（任意代码判据）拒收；subject 越出 R2
   四 subject 体系拒收；source 缺失或形态非法拒收——判据逻辑仍人工；
3. 棘轮效果：立案后 `validateCaseFirst` 对该 subject 由 missing 转 covered
   （case 覆盖只进不退）；
4. 来源钩子 `fromRegression`：C1 的 case_regressions 形态逐例转注册、
   按例去重；case_unevidenced（未量出）不是失败、不立案；
5. 注册表隔离：每例前后清空 case 注册表与棘轮去重账本，不污染其他测试。
"""
import pytest

from neurova.benchmark.suite_eval import (
    CRITERION_TEMPLATE_ATTR,
    clearEvalCases,
    exactAnswer,
    listEvalCases,
    markersPresent,
    validateCaseFirst,
)

#: 立案出处统一用事故/Issue 形态（kind ∈ incident|issue|review，ref 非空）。
SOURCE_INCIDENT = {"kind": "incident", "ref": "rsi-round-42/case-regression"}
SOURCE_ISSUE = {"kind": "issue", "ref": "#501"}

_RATCHET_PREFIX = "ratchet-"


@pytest.fixture(autouse=True)
def _isolatedRegistries():
    """case 注册表与棘轮去重账本都是模块级全局：每例前后清空，互不串扰。"""
    from neurova.benchmark import ratchet

    clearEvalCases()
    ratchet.resetRatchetSink()
    yield
    clearEvalCases()
    ratchet.resetRatchetSink()


def _sink():
    from neurova.benchmark import ratchet

    return ratchet.getRatchetSink()


def _ratchetCases():
    return [c for c in listEvalCases() if c.case_id.startswith(_RATCHET_PREFIX)]


# ── 注册成功：进 suite_eval 注册表，字段对齐 R2 体系 ────────────────

def testRegisterFailureCaseSuccess():
    status = _sink().registerFailureCase(
        subjectId="soul",
        prompt="请自我介绍：你是谁、你的职责是什么？",
        check=markersPresent(("我是", "职责")),
        sourceRef=SOURCE_INCIDENT,
        dedupKey="soul|incident:rsi-round-42|self-intro-missing",
    )
    assert status == "registered"

    cases = _ratchetCases()
    assert len(cases) == 1
    case = cases[0]
    assert case.subject_id == "soul"
    assert case.source == SOURCE_INCIDENT
    assert case.suite_id == "model-visible-text-v1"  # 与 R2 首批同 suite
    assert case.prompt.strip()
    # 判据可执行且咬合：缺要素红、齐要素绿
    passed, score, _ = case.check("我是凯。")
    assert passed is False
    passed, score, _ = case.check("我是凯，我的职责是协助你完成日常任务。")
    assert passed is True and score == 1.0


def testCaseIdDeterministicFromDedupKey():
    """同 dedupKey 永远映射同一 case_id（确定性幂等的机制基础）。"""
    from neurova.benchmark import ratchet

    _sink().registerFailureCase(
        subjectId="soul", prompt="p", check=exactAnswer("15"),
        sourceRef=SOURCE_INCIDENT, dedupKey="k1",
    )
    caseId = _ratchetCases()[0].case_id
    assert caseId == ratchet.caseIdForDedup("k1")


# ── 去重：同 dedupKey 不重复立案 ───────────────────────────────────

def testDuplicateDedupKeyNotRegisteredTwice():
    sink = _sink()
    kwargs = dict(
        subjectId="soul", prompt="p", check=exactAnswer("15"),
        sourceRef=SOURCE_INCIDENT,
    )
    assert sink.registerFailureCase(dedupKey="sig-1", **kwargs) == "registered"
    assert sink.registerFailureCase(dedupKey="sig-1", **kwargs) == "duplicate"
    assert len(_ratchetCases()) == 1
    # 不同失败签名仍可立案（同 subject 多件 case 合法）
    assert sink.registerFailureCase(dedupKey="sig-2", **kwargs) == "registered"
    assert len(_ratchetCases()) == 2


def testDuplicateRecognizedEvenAfterDedupLedgerReset():
    """去重账本被清而 case 注册表仍在：case_id 撞册仍判 duplicate，不炸。"""
    from neurova.benchmark import ratchet

    sink = _sink()
    kwargs = dict(
        subjectId="soul", prompt="p", check=exactAnswer("15"),
        sourceRef=SOURCE_INCIDENT, dedupKey="sig-1",
    )
    assert sink.registerFailureCase(**kwargs) == "registered"
    ratchet.resetRatchetSink()  # 只清去重账本，注册表保留
    assert sink.registerFailureCase(**kwargs) == "duplicate"
    assert len(_ratchetCases()) == 1


# ── 裁判件保护：判据逻辑仍人工 ─────────────────────────────────────

def testNonWhitelistCheckRejected():
    """任意代码判据（无白名单模板标记）拒收，不立案。"""

    def arbitraryCheck(answer):
        return ("机密" not in str(answer)), 1.0, {}

    status = _sink().registerFailureCase(
        subjectId="soul", prompt="p", check=arbitraryCheck,
        sourceRef=SOURCE_INCIDENT, dedupKey="sig-custom",
    )
    assert status == "rejected"
    assert _ratchetCases() == []


def testCheckNoneRejected():
    status = _sink().registerFailureCase(
        subjectId="soul", prompt="p", check=None,
        sourceRef=SOURCE_INCIDENT, dedupKey="sig-none",
    )
    assert status == "rejected"
    assert _ratchetCases() == []


def testWhitelistTemplatesAreTaggedAndFrozen():
    """白名单是 forbidden 语义的模块常量；模板实例带标记（核验机制基础）。"""
    from neurova.benchmark import ratchet

    assert isinstance(ratchet.CRITERION_TEMPLATE_WHITELIST, frozenset)
    assert ratchet.CRITERION_TEMPLATE_WHITELIST == {"exactAnswer", "markersPresent"}
    assert getattr(exactAnswer("x"), CRITERION_TEMPLATE_ATTR, None) == "exactAnswer"
    assert getattr(markersPresent(("a",)), CRITERION_TEMPLATE_ATTR, None) == "markersPresent"


# ── subject 对齐 R2 四 subject 体系 ────────────────────────────────

def testSubjectOutsideFourSubjectSystemRejected():
    """RSI 参数例 id 等越界 subject 拒收：自动通道不能自创守卫面。"""
    status = _sink().registerFailureCase(
        subjectId="tm_decay_forgetting_band", prompt="p", check=exactAnswer("15"),
        sourceRef=SOURCE_INCIDENT, dedupKey="sig-rsi-case",
    )
    assert status == "rejected"
    assert _ratchetCases() == []


def testSubjectEmptyRejected():
    status = _sink().registerFailureCase(
        subjectId="", prompt="p", check=exactAnswer("15"),
        sourceRef=SOURCE_INCIDENT, dedupKey="sig-empty-subject",
    )
    assert status == "rejected"
    assert _ratchetCases() == []


# ── source 强制 {kind, ref}，缺一即拒 ──────────────────────────────

def testMissingOrInvalidSourceRejected():
    sink = _sink()
    badSources = [
        None,
        {},
        {"kind": "incident"},              # 缺 ref
        {"ref": "x"},                      # 缺 kind
        {"kind": "chat", "ref": "x"},      # kind 不在 incident|issue|review
        {"kind": "incident", "ref": "  "},  # ref 空白
    ]
    for i, bad in enumerate(badSources):
        status = sink.registerFailureCase(
            subjectId="soul", prompt="p", check=exactAnswer("15"),
            sourceRef=bad, dedupKey=f"sig-bad-source-{i}",
        )
        assert status == "rejected", f"source={bad!r} 应拒收"
    assert _ratchetCases() == []


# ── prompt / dedupKey 必填 ─────────────────────────────────────────

def testEmptyPromptRejected():
    sink = _sink()
    assert sink.registerFailureCase(
        subjectId="soul", prompt="   ", check=exactAnswer("15"),
        sourceRef=SOURCE_INCIDENT, dedupKey="sig-empty-prompt",
    ) == "rejected"
    assert sink.registerFailureCase(
        subjectId="soul", prompt="p", check=exactAnswer("15"),
        sourceRef=SOURCE_INCIDENT, dedupKey="  ",
    ) == "rejected"
    assert _ratchetCases() == []


# ── 棘轮效果：validateCaseFirst 由 missing 转 covered ──────────────

def testRatchetEffectValidateCaseFirstMissingToCovered():
    subject = "behavior_rules"
    before = validateCaseFirst([subject])
    assert before["missing"] == [subject]  # 立案前：无 case 覆盖

    status = _sink().registerFailureCase(
        subjectId=subject,
        prompt="请列出你当前遵循的行为规则：什么必须做、什么不要做？",
        check=markersPresent(("必须", "不要")),
        sourceRef=SOURCE_ISSUE,
        dedupKey="behavior_rules|issue:501|deontic-missing",
    )
    assert status == "registered"

    after = validateCaseFirst([subject])
    assert after["covered"] == [subject]  # 立案后：覆盖（棘轮只进不退）
    assert after["missing"] == []


# ── 来源钩子：C1 case_regressions 形态 → 逐例转注册 ────────────────

def testFromRegressionRegistersPerRegressedCase():
    from neurova.benchmark import ratchet

    metrics = {
        "case_regressions": ["case_a", "case_b"],
        "case_unevidenced": ["case_c"],  # 未量出 ≠ 失败，不立案
    }
    statuses = ratchet.fromRegression(
        metrics,
        subjectId="rules_sections",
        prompt="请给出恒定规则段的四个段标题。",
        check=markersPresent(("## 工具使用规则", "## 环境", "## 记忆写入规则", "## 桌面操作纪律")),
        sourceRef={"kind": "incident", "ref": "rsi-round-7"},
    )
    assert statuses == {"case_a": "registered", "case_b": "registered"}
    assert len(_ratchetCases()) == 2
    # unevidenced 例不占去重账，也不立案
    subjects = {c.subject_id for c in _ratchetCases()}
    assert subjects == {"rules_sections"}


def testFromRegressionReplayIsDuplicate():
    """同一批回归重放：按例去重全 duplicate，不重复立案。"""
    from neurova.benchmark import ratchet

    metrics = {"case_regressions": ["case_a", "case_b"]}
    kwargs = dict(
        subjectId="rules_sections", prompt="p",
        check=markersPresent(("## 环境",)),
        sourceRef={"kind": "incident", "ref": "rsi-round-7"},
    )
    first = ratchet.fromRegression(metrics, **kwargs)
    assert set(first.values()) == {"registered"}
    replay = ratchet.fromRegression(metrics, **kwargs)
    assert replay == {"case_a": "duplicate", "case_b": "duplicate"}
    assert len(_ratchetCases()) == 2


def testFromRegressionEmptyOrMalformedMetricsIsNoop():
    from neurova.benchmark import ratchet

    kwargs = dict(
        subjectId="soul", prompt="p", check=exactAnswer("15"),
        sourceRef=SOURCE_INCIDENT,
    )
    assert ratchet.fromRegression(None, **kwargs) == {}
    assert ratchet.fromRegression({}, **kwargs) == {}
    assert ratchet.fromRegression({"case_regressions": []}, **kwargs) == {}
    assert ratchet.fromRegression({"case_regressions": "not-a-list"}, **kwargs) == {}
    assert _ratchetCases() == []


def testFromRegressionStillGatedBySubjectAndCriterionRules():
    """钩子不走后门：subject 越界 / 判据非白名单照样拒收。"""
    from neurova.benchmark import ratchet

    statuses = ratchet.fromRegression(
        {"case_regressions": ["tm_x"]},
        subjectId="tm_x",  # 越出 R2 四 subject 体系
        prompt="p", check=exactAnswer("15"), sourceRef=SOURCE_INCIDENT,
    )
    assert statuses == {"tm_x": "rejected"}

    def arbitraryCheck(answer):
        return True, 1.0, {}

    statuses = ratchet.fromRegression(
        {"case_regressions": ["case_a"]},
        subjectId="soul", prompt="p", check=arbitraryCheck,
        sourceRef=SOURCE_INCIDENT,
    )
    assert statuses == {"case_a": "rejected"}
    assert _ratchetCases() == []
