# -*- coding: utf-8 -*-
"""evals「先 case 后修」纪律单测（参照系 ac 追平计划批三 E1）。

钉住两件事：
1. 机制面（neurova/benchmark/suite_eval.py）：
   - EvalCase 注册表：注册 / 重复 case_id 拒绝 / 按 suite 列取；
   - validateCaseFirst：改动面里每个模型可见文本 subject_id 必须有已注册
     eval case 覆盖（纪律检查单源）；
   - assertCaseRedGreen：旧文本下判据必须红、新文本下必须绿——
     「先 case 后修」的自检器；
   - source 必填（kind/ref 缺一即 ValueError）；
   - runSuite cost_note 透传落事实记录（手动跑成本标注，不影响既有字段）。
2. 文档面：三落点（AGENTS.md / .cnb/settings.yml / CONTRIBUTING.md）同步
   「先 case 后修」纪律（自建轻量断言，不修改既有守卫）。

D-H 口径：评测手动跑 + 成本标注，CI 只跑判据单测，不接付费模型跑。
"""
import io
from pathlib import Path

import pytest

from neurova.benchmark.suite_eval import (
    EvalCase,
    assertCaseRedGreen,
    clearEvalCases,
    exactAnswer,
    listEvalCases,
    registerEvalCase,
    runSuite,
    validateCaseFirst,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def _clearCaseRegistry():
    """eval case 注册表是模块级全局：每个用例前清空，保证互不串扰。"""
    clearEvalCases()
    yield
    clearEvalCases()


def _makeCase(
    caseId: str = "case-1",
    suiteId: str = "reasoning-v1",
    subjectId: str = "tool:web_search.description",
    check=None,
    source: dict | None = None,
    costHint: dict | None = None,
) -> EvalCase:
    return EvalCase(
        case_id=caseId,
        suite_id=suiteId,
        prompt="小明有 12 个苹果，送给小红 5 个，又买了 8 个。现在有几个苹果？",
        check=check or exactAnswer("15"),
        subject_id=subjectId,
        source=source if source is not None else {"kind": "issue", "ref": "#331"},
        cost_hint=costHint,
    )


# ── 注册表：注册 / 重复拒绝 / 按 suite 列取 ─────────────────────────

def testRegisterAndListBySuite():
    caseA = _makeCase(caseId="case-a", suiteId="reasoning-v1")
    caseB = _makeCase(caseId="case-b", suiteId="coding-v1", subjectId="tool:code_run.description")
    registerEvalCase(caseA)
    registerEvalCase(caseB)

    allCases = listEvalCases()
    assert {c.case_id for c in allCases} == {"case-a", "case-b"}

    reasoningCases = listEvalCases("reasoning-v1")
    assert [c.case_id for c in reasoningCases] == ["case-a"]

    codingCases = listEvalCases("coding-v1")
    assert [c.case_id for c in codingCases] == ["case-b"]

    assert listEvalCases("no-such-suite") == []


def testRegisterEvalCasePreservesFields():
    case = _makeCase(costHint={"model": "deepseek-v4.1-flash", "est_tokens": 1200})
    registerEvalCase(case)
    loaded = listEvalCases("reasoning-v1")[0]
    assert loaded.case_id == "case-1"
    assert loaded.suite_id == "reasoning-v1"
    assert loaded.subject_id == "tool:web_search.description"
    assert loaded.source == {"kind": "issue", "ref": "#331"}
    assert loaded.cost_hint == {"model": "deepseek-v4.1-flash", "est_tokens": 1200}
    # 判据可执行
    passed, score, _details = loaded.check("15")
    assert passed is True and score == 1.0


def testDuplicateCaseIdRejected():
    registerEvalCase(_makeCase(caseId="case-1", suiteId="reasoning-v1"))
    with pytest.raises(ValueError, match="case-1"):
        registerEvalCase(_makeCase(caseId="case-1", suiteId="coding-v1"))


# ── validateCaseFirst：纪律检查单源 ────────────────────────────────

def testValidateCaseFirstAllCoveredGivesEmptyMissing():
    registerEvalCase(_makeCase(caseId="case-a", subjectId="tool:web_search.description"))
    registerEvalCase(_makeCase(caseId="case-b", suiteId="coding-v1", subjectId="tool:code_run.description"))

    report = validateCaseFirst(["tool:web_search.description", "tool:code_run.description"])
    assert report["missing"] == []
    assert report["covered"] == ["tool:code_run.description", "tool:web_search.description"]


def testValidateCaseFirstNamesTheMissingSubject():
    registerEvalCase(_makeCase(caseId="case-a", subjectId="tool:web_search.description"))

    report = validateCaseFirst(["tool:web_search.description", "tool:code_run.description"])
    assert report["covered"] == ["tool:web_search.description"]
    assert report["missing"] == ["tool:code_run.description"]


def testValidateCaseFirstCrossSuiteSummary():
    """覆盖判定跨 suite 汇总：任一 suite 的 case 覆盖即算 covered。"""
    registerEvalCase(_makeCase(caseId="case-a", suiteId="reasoning-v1", subjectId="tool:web_search.description"))
    registerEvalCase(_makeCase(caseId="case-b", suiteId="coding-v1", subjectId="tool:code_run.description"))

    changed = ["tool:web_search.description", "tool:code_run.description", "rubric:memory-v1"]
    report = validateCaseFirst(changed)
    assert report["covered"] == ["tool:code_run.description", "tool:web_search.description"]
    assert report["missing"] == ["rubric:memory-v1"]

    # suite_ids 过滤：只看 reasoning-v1 时，coding-v1 的覆盖不再计入
    filtered = validateCaseFirst(changed, suiteIds=["reasoning-v1"])
    assert filtered["covered"] == ["tool:web_search.description"]
    assert filtered["missing"] == ["rubric:memory-v1", "tool:code_run.description"]


# ── assertCaseRedGreen：红→绿自检器 ────────────────────────────────

def testAssertCaseRedGreenPassesWhenOldRedNewGreen():
    case = _makeCase(check=exactAnswer("15"))
    # 旧文本：模型可见文本缺关键条件 → 答非 15（红）；新文本：补齐后答 15（绿）
    assertCaseRedGreen(
        case,
        oldAnswerFn=lambda prompt: "13",
        newAnswerFn=lambda prompt: "15",
    )


def testAssertCaseRedGreenRejectsOldAlreadyGreen():
    case = _makeCase(check=exactAnswer("15"))
    with pytest.raises(AssertionError) as excinfo:
        assertCaseRedGreen(
            case,
            oldAnswerFn=lambda prompt: "15",  # 旧文本已绿 → 违反「先红」
            newAnswerFn=lambda prompt: "15",
        )
    message = str(excinfo.value)
    assert "case-1" in message
    assert "旧" in message  # 指名是哪一态不满足


def testAssertCaseRedGreenRejectsNewNotGreen():
    case = _makeCase(check=exactAnswer("15"))
    with pytest.raises(AssertionError) as excinfo:
        assertCaseRedGreen(
            case,
            oldAnswerFn=lambda prompt: "13",
            newAnswerFn=lambda prompt: "13",  # 新文本仍未绿 → 违反「后绿」
        )
    message = str(excinfo.value)
    assert "case-1" in message
    assert "新" in message  # 指名是哪一态不满足


# ── source 必填 ────────────────────────────────────────────────────

def testSourceKindRequired():
    with pytest.raises(ValueError):
        registerEvalCase(_makeCase(source={"ref": "#331"}))


def testSourceRefRequired():
    with pytest.raises(ValueError):
        registerEvalCase(_makeCase(source={"kind": "issue"}))


def testSourceKindMustBeKnownKind():
    with pytest.raises(ValueError):
        registerEvalCase(_makeCase(source={"kind": "chat", "ref": "#331"}))


def testSourceEmptyRefRejected():
    with pytest.raises(ValueError):
        registerEvalCase(_makeCase(source={"kind": "incident", "ref": "  "}))


# ── runSuite cost_note 透传 ────────────────────────────────────────

def _oneTaskSuite():
    from neurova.benchmark.suite_eval import SuiteTask
    return [SuiteTask(task_id="t1", prompt="q1", check=exactAnswer("a1"))]


def testRunSuiteCostNotePassedThroughIntoRecord():
    costNote = {"model": "deepseek-v4.1-flash", "est_tokens": 800, "run_by": "manual"}
    report = runSuite(_oneTaskSuite(), answerFn=lambda p: "a1", costNote=costNote)
    assert report["cost_note"] == costNote
    # 既有字段不受影响
    assert report["status"] == "completed"
    assert report["tasks_total"] == 1
    assert report["tasks_correct"] == 1
    assert report["score"] == 1.0


def testRunSuiteWithoutCostNoteKeepsLegacyShape():
    report = runSuite(_oneTaskSuite(), answerFn=lambda p: "a1")
    assert "cost_note" not in report
    assert report["status"] == "completed"


# ── 三落点一致性守卫（自建轻量断言，不修改既有守卫） ────────────────

DISCIPLINE_MARKERS = (
    "先 case 后修",
    "CI 只跑判据单测",
)


def _read(*parts) -> str:
    return io.open(PROJECT_ROOT.joinpath(*parts), encoding="utf-8").read()


def testAgentsMdStatesCaseFirstDiscipline():
    text = _read("AGENTS.md")
    for marker in DISCIPLINE_MARKERS:
        assert marker in text, f"AGENTS.md 缺「{marker}」纪律句"


def testContributingStatesCaseFirstDiscipline():
    text = _read("CONTRIBUTING.md")
    for marker in DISCIPLINE_MARKERS:
        assert marker in text, f"CONTRIBUTING.md 缺「{marker}」纪律句"


def testSettingsYmlEveryRoleStatesCaseFirstDiscipline():
    yaml = pytest.importorskip("yaml")
    doc = yaml.safe_load(_read(".cnb", "settings.yml")) or {}
    roles = (doc.get("npc") or {}).get("roles") or []
    assert roles, ".cnb/settings.yml 未声明任何 NPC 角色"
    problems = []
    for role in roles:
        prompt = (role or {}).get("prompt") or ""
        missing = [m for m in DISCIPLINE_MARKERS if m not in prompt]
        if missing:
            problems.append(f"{(role or {}).get('name')}: 缺 {missing}")
    assert not problems, (
        "NPC 角色 prompt 未同步「先 case 后修」纪律:\n  " + "\n  ".join(problems)
    )
