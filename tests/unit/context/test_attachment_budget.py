# -*- coding: utf-8 -*-
"""P1-5 附件预算单源（上下文工程十轴 · 轴 7）：`planAttachmentInjection` 判据与注入接线。

预算语义（"附件永不触发压缩"）：附件正文在 `build_context` **之前**并入
`user_input`，其计划总量（含预览与句柄说明）不得越过压缩触发线以下的剩余空间。

判定面：
- 预算内 → `full`（全文并入）；
- 超预算 → `preview`（保留开头的截断预览 + `TRUNCATION_MARK` + 句柄说明，含 file_id）；
- 多附件按序贪心：先到先得占满剩余空间，总量 ≤ 预算；
- None/负值预算 → 透传（与无预算行为一致，不造数）；
- 空附件 → 空 plan；同输入同计划（确定性）。
"""

from __future__ import annotations

from types import SimpleNamespace

from neurova.context.attachment_budget import (
    DECISION_FULL,
    DECISION_PREVIEW,
    AttachmentBudgetItem,
    planAttachmentInjection,
)
from neurova.context.fold_resolution import TRUNCATION_MARK


def _lenEstimator(text: str) -> int:
    """确定性测试尺：1 字符 = 1 token（不依赖 tiktoken，断言可精算）。"""
    return len(text or "")


def _item(index: int, bodyLen: int) -> AttachmentBudgetItem:
    body = "x" * bodyLen
    return AttachmentBudgetItem(
        file_id=f"file_{index}",
        filename=f"doc{index}.txt",
        file_type="text",
        full_text=f"[用户上传了文件 doc{index}.txt，以下为该文件的完整内容]\n{body}",
        body=body,
    )


class TestPlanAttachmentInjection:
    def test_budgetFits_allFull(self):
        plan = planAttachmentInjection(
            attachments=[_item(1, 50), _item(2, 60)],
            remaining_budget_tokens=10_000,
            estimator=_lenEstimator,
        )
        assert not plan.passthrough
        assert [d.decision for d in plan.decisions] == [DECISION_FULL, DECISION_FULL]
        assert plan.decisions[0].injected_text == _item(1, 50).full_text
        assert plan.total_used_tokens <= 10_000
        assert plan.isValid()

    def test_overBudget_becomesPreviewWithHandle(self):
        plan = planAttachmentInjection(
            attachments=[_item(1, 1000)],
            remaining_budget_tokens=300,
            estimator=_lenEstimator,
        )
        d = plan.decisions[0]
        assert d.decision == DECISION_PREVIEW
        assert 0 < d.preview_chars < 1000
        assert d.truncated_chars == 1000 - d.preview_chars
        assert TRUNCATION_MARK in d.injected_text, f"截断必须对模型可见：{d.injected_text!r}"
        assert "file_1" in d.injected_text
        assert plan.total_used_tokens <= 300
        assert plan.isValid()

    def test_multipleAttachments_greedyInOrder_totalWithinBudget(self):
        """按序贪心：前者先得，后者只能吃剩余；无论预算多紧，总量不超。"""
        plan = planAttachmentInjection(
            attachments=[_item(1, 100), _item(2, 100), _item(3, 100)],
            remaining_budget_tokens=250,
            estimator=_lenEstimator,
        )
        d1, d2, d3 = plan.decisions
        assert d1.decision == DECISION_FULL
        assert d2.decision == DECISION_PREVIEW
        assert 0 < d2.preview_chars < 100, "第二个附件应被截断但保留开头"
        assert d3.decision == DECISION_PREVIEW
        assert d3.preview_chars == 0, "剩余空间被前两个占满，第三个应颗粒无收"
        assert plan.total_used_tokens <= 250
        assert plan.isValid()

    def test_noneBudget_passthrough(self):
        full = _item(1, 500).full_text
        plan = planAttachmentInjection(
            attachments=[_item(1, 500)], remaining_budget_tokens=None, estimator=_lenEstimator
        )
        assert plan.passthrough
        assert plan.decisions[0].decision == DECISION_FULL
        assert plan.decisions[0].injected_text == full
        assert plan.isValid()

    def test_negativeBudget_passthrough(self):
        plan = planAttachmentInjection(
            attachments=[_item(1, 500)], remaining_budget_tokens=-1, estimator=_lenEstimator
        )
        assert plan.passthrough
        assert plan.decisions[0].decision == DECISION_FULL
        assert plan.decisions[0].injected_text == _item(1, 500).full_text

    def test_emptyAttachments_emptyPlan(self):
        plan = planAttachmentInjection(
            attachments=[], remaining_budget_tokens=100, estimator=_lenEstimator
        )
        assert plan.decisions == []
        assert plan.total_used_tokens == 0

    def test_sameInput_samePlan(self):
        def build():
            return planAttachmentInjection(
                attachments=[_item(1, 300), _item(2, 300)],
                remaining_budget_tokens=400,
                estimator=_lenEstimator,
            )

        assert build().toDict() == build().toDict()

    def test_handleNote_containsFileId(self):
        """句柄说明必须携带 file_id（附件取用凭证只有句柄，服务端路径不对外）。"""
        plan = planAttachmentInjection(
            attachments=[_item(7, 900)], remaining_budget_tokens=200, estimator=_lenEstimator
        )
        d = plan.decisions[0]
        assert d.decision == DECISION_PREVIEW
        assert "file_7" in d.handle_note
        assert "附件句柄" in d.handle_note
        assert "file_7" in d.injected_text

    def test_hardConstraint_holdsAcrossBudgets(self):
        """硬约束扫荡：任意预算下计划总量（含预览与句柄说明）都不得超。"""
        for budget in (10, 50, 120, 400, 5000):
            plan = planAttachmentInjection(
                attachments=[_item(1, 800), _item(2, 800), _item(3, 800)],
                remaining_budget_tokens=budget,
                estimator=_lenEstimator,
            )
            assert plan.total_used_tokens <= budget, (
                f"budget={budget} 时计划总量 {plan.total_used_tokens} 超预算"
            )
            assert plan.isValid()

    def test_zeroBodyItem_overBudget_neverExceeds(self):
        """无正文附件（通知类）在极小预算下不得把总量顶过预算。"""
        item = AttachmentBudgetItem(
            file_id="file_v",
            filename="clip.mp4",
            file_type="video",
            full_text="[用户上传了视频: clip.mp4（已抽取 3 帧随本轮请求附上）]",
            body="",
        )
        plan = planAttachmentInjection(
            attachments=[item], remaining_budget_tokens=10, estimator=_lenEstimator
        )
        d = plan.decisions[0]
        assert plan.total_used_tokens <= 10
        assert plan.isValid()
        # 10 token 连句柄留痕都放不下 → 诚实空置，不硬塞超预算文本
        assert d.injected_text == "" or "file_v" in d.injected_text

    def test_planToDict_readable(self):
        plan = planAttachmentInjection(
            attachments=[_item(1, 900)], remaining_budget_tokens=200, estimator=_lenEstimator
        )
        data = plan.toDict()
        assert data["passthrough"] is False
        assert data["remaining_budget_tokens"] == 200
        first = data["decisions"][0]
        assert first["decision"] == DECISION_PREVIEW
        assert {"decision", "used_tokens", "preview_chars", "handle_note"} <= set(first.keys())


class TestInjectionWiring:
    """接线面：`injectAttachmentsIntoInput` 消费预算计划（chat_pipeline 不改）。"""

    def _pipeline(self, model: str, fileBytes: bytes) -> SimpleNamespace:
        p = SimpleNamespace()
        p._current_model_name = lambda: model
        p._read_attachment_bytes = lambda file_id: fileBytes
        return p

    def _attachment(self, fileId: str, filename: str) -> dict:
        return {
            "file_id": fileId,
            "filename": filename,
            "file_type": "text",
            "mime_type": "text/plain",
            "size": 1,
            "path": f"/tmp/{filename}",
        }

    def test_smallText_withinBudget_fullInjection(self):
        from neurova.agent.attachment_turn_injection import injectAttachmentsIntoInput

        pipeline = self._pipeline("gpt-4o", "短文件内容".encode("utf-8"))
        text, vision = injectAttachmentsIntoInput(
            pipeline, "分析这份文件", [self._attachment("f_small", "note.txt")]
        )
        assert "短文件内容" in text
        assert TRUNCATION_MARK not in text
        assert vision == []

    def test_hugeText_overBudget_previewWithHandle_andWithinTriggerLine(self):
        from neurova.agent.attachment_turn_injection import injectAttachmentsIntoInput
        from neurova.context.token_estimator import estimate_tokens

        huge = "y" * 200_000
        pipeline = self._pipeline("no-such-model-xyz", huge.encode("utf-8"))
        text, vision = injectAttachmentsIntoInput(
            pipeline, "分析", [self._attachment("f_huge", "big.txt")]
        )
        assert TRUNCATION_MARK in text, "超预算附件必须以截断预览形态注入"
        assert "f_huge" in text, "句柄必须随预览交给模型"
        assert "附件句柄" in text
        assert len(text) < len(huge)
        # 预算语义：注入后的本轮文本不越过该模型的压缩触发线（预算×0.85）。
        # 触发线用与接线完全相同的解析链取值，两侧同尺。
        from neurova.context_pool import CONTEXT_COMPACT_TRIGGER_RATIO, ContextPool

        trigger = int(
            ContextPool.get_token_budget_for_model("no-such-model-xyz")
            * CONTEXT_COMPACT_TRIGGER_RATIO
        )
        assert estimate_tokens(text) <= trigger + estimate_tokens("分析") + 8

    def test_noModel_passthrough_unchanged(self):
        from neurova.agent.attachment_turn_injection import injectAttachmentsIntoInput

        payload = "完整文件内容应当原样保留".encode("utf-8")
        pipeline = self._pipeline("", payload)
        text, vision = injectAttachmentsIntoInput(
            pipeline, "原文", [self._attachment("f_p", "keep.txt")]
        )
        assert "完整文件内容应当原样保留" in text
        assert TRUNCATION_MARK not in text
        assert vision == []
