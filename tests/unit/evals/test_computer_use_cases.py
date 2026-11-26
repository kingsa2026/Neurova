# -*- coding: utf-8 -*-
"""computer_use 工具描述面的 eval case（C5，先 case 后修纪律的立案面）。

subject：computer_type / computer_paste 工具描述（builtin_tools.py，模型可见）。
判据为确定性标记判别（对被检文本本身判别，不调模型）。
"""

import pytest

from neurova.benchmark.suite_eval import (
    EvalCase,
    assertCaseRedGreen,
    listEvalCases,
    markersPresent,
    registerEvalCase,
)

CASE_SUITE_ID = "model-visible-text-v1"


def _typeDescriptionText() -> str:
    from neurova.builtin_tools import _BUILTIN_SCHEMAS

    return str(_BUILTIN_SCHEMAS["computer_type"].get("description") or "")


@pytest.fixture(scope="module", autouse=True)
def _registerCases():
    from neurova.benchmark.computer_use_cases import registerComputerUseCases

    registerComputerUseCases()
    yield


def _caseById(caseId: str):
    matched = [case for case in listEvalCases(CASE_SUITE_ID)
               if case.case_id == caseId]
    assert matched, f"case 未注册: {caseId}"
    return matched[0]


class TestComputerTypeGuidanceCase:
    def test_caseRegisteredWithIncidentSource(self):
        case = _caseById("computer-type-paste-guidance-v1")
        assert case.subject_id == "computer_type_description"
        assert case.source["kind"] == "incident"
        assert "osworld" in case.source["ref"].lower(), "case 须标注 OSWorld 失败分析出处"

    def test_bitesOldDescriptionThenGreenOnNew(self):
        case = _caseById("computer-type-paste-guidance-v1")
        assertCaseRedGreen(
            case,
            oldAnswerFn=lambda p: "键盘输入文本",
            newAnswerFn=lambda p: _typeDescriptionText(),
        )

    def test_bitesRealAssembledDescription(self):
        """真实 schema 文本自检：判据在真实描述上必须通过。"""
        case = _caseById("computer-type-paste-guidance-v1")
        passed, _, _ = case.check(_typeDescriptionText())
        assert passed, f"真实描述缺引导标记：{_typeDescriptionText()!r}"

    def test_pasteDescriptionKeepsLongTextGuidance(self):
        """computer_paste 侧既有引导（适合长文本）不得丢失（对账钉子）。"""
        from neurova.builtin_tools import _BUILTIN_SCHEMAS

        description = str(_BUILTIN_SCHEMAS["computer_paste"].get("description") or "")
        passed, _, _ = markersPresent(("长文本", "ctrl+v"))(description)
        assert passed, "computer_paste 描述须保留长文本/ctrl+v 引导"


class TestDocEditRoutingCase:
    """C7 脚本通道与 GUI 车道路由约定（OSWorld M1 反例教训）：表格值/公式
    批量写入走 doc_edit 直写（自动回读校验）；样式/合并/图表等需要视觉
    确认的界面态走 GUI 动作。判据对真实描述文本判别路由规则存在。"""

    def _docEditDescription(self) -> str:
        from neurova.builtin_tools import _BUILTIN_SCHEMAS

        return str(_BUILTIN_SCHEMAS["computer_doc_edit"].get("description") or "")

    def test_caseRegisteredWithReviewSource(self):
        case = _caseById("computer-doc-edit-routing-v1")
        assert case.subject_id == "computer_doc_edit_description"
        assert case.source["kind"] in ("incident", "review")

    def test_bitesOldDescriptionThenGreenOnNew(self):
        case = _caseById("computer-doc-edit-routing-v1")
        assertCaseRedGreen(
            case,
            oldAnswerFn=lambda p: "【结构化直写】对工作区内的 xlsx 文件批量写入值。",
            newAnswerFn=lambda p: self._docEditDescription(),
        )

    def test_realDescriptionCarriesRoutingRule(self):
        passed, _, details = markersPresent(("样式", "GUI"))(self._docEditDescription())
        assert passed, f"doc_edit 描述缺路由规则：{details!r}"
