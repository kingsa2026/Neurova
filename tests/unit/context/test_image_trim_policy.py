# -*- coding: utf-8 -*-
"""压缩纪律·图像分档裁剪（reference_af 借鉴项 P1-6）——红→绿 TDD 契约测试。

两条纪律（上下文分级裁剪）：
1.「图像先于文本丢弃」：窗口超预算时先摘旧图的图像部件（换占位文本），
  文本轮不动——能靠裁图回到预算内就不折叠文本；
2.「长上下文模型只裁旧图」：图像保留窗口按模型上下文窗口分档——
  长上下文模型只裁保留窗口之外的旧图，近期图像永不裁；窗口未知/短上下文
  按基础档（model_limits.MULTIMODAL_IMAGE_RETAIN_PER_TURN 单源）。

钉子纪律：分档阈值/保留窗口全部走具名常量，不用字面量数字。
"""

from __future__ import annotations

import copy

import pytest

from neurova.context.window_compactor import WindowTokenMeter, compact_window
from neurova.llm import model_limits


def _imgMsg(text: str) -> dict:
    return {
        "role": "user",
        "content": [
            {"type": "text", "text": text},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
        ],
    }


def _textMsg(text: str) -> dict:
    return {"role": "user", "content": text}


def _hasImage(msg: dict) -> bool:
    content = msg.get("content")
    return isinstance(content, list) and any(
        isinstance(p, dict) and p.get("type") == "image_url" for p in content
    )


def _placeholderCount(msgs) -> int:
    n = 0
    for m in msgs:
        content = m.get("content") if isinstance(m, dict) else None
        if isinstance(content, list):
            n += sum(
                1
                for p in content
                if isinstance(p, dict) and p.get("type") == "text" and "已省略" in str(p.get("text"))
            )
    return n


# ── 分档窗口解析 ─────────────────────────────────────────────────

class TestResolveImageKeepWindow:
    def test_tierConstantsNamedAndOrdered(self):
        """钉子纪律：分档阈值/窗口必须是具名常量且单调递增。"""
        from neurova.context.image_trim_policy import (
            LONG_CONTEXT_IMAGE_KEEP_WINDOW,
            LONG_CONTEXT_WINDOW_TOKENS,
            ULTRA_LONG_CONTEXT_IMAGE_KEEP_WINDOW,
            ULTRA_LONG_CONTEXT_WINDOW_TOKENS,
        )

        assert 0 < model_limits.MULTIMODAL_IMAGE_RETAIN_PER_TURN <= LONG_CONTEXT_IMAGE_KEEP_WINDOW
        assert LONG_CONTEXT_IMAGE_KEEP_WINDOW <= ULTRA_LONG_CONTEXT_IMAGE_KEEP_WINDOW
        assert 0 < LONG_CONTEXT_WINDOW_TOKENS < ULTRA_LONG_CONTEXT_WINDOW_TOKENS

    def test_unknownModelFallsBackToBaseSingleSource(self, monkeypatch):
        """未知模型不放宽：按基础档（单源，调用时读）——裁剪纪律宁紧勿松。"""
        from neurova.context.image_trim_policy import resolveImageKeepWindow

        monkeypatch.setattr(model_limits, "MULTIMODAL_IMAGE_RETAIN_PER_TURN", 3)
        assert resolveImageKeepWindow("") == 3
        assert resolveImageKeepWindow("unknown-model-x") == 3

    def test_shortContextModelKeepsBaseWindow(self):
        """128K 档（gpt-4o）未达长上下文线 → 基础保留窗。"""
        from neurova.context.image_trim_policy import resolveImageKeepWindow

        assert resolveImageKeepWindow("gpt-4o") == model_limits.MULTIMODAL_IMAGE_RETAIN_PER_TURN

    def test_longContextModelWiderWindow(self):
        """200K 档（claude-sonnet-4）→ 长上下文档保留窗。"""
        from neurova.context.image_trim_policy import (
            LONG_CONTEXT_IMAGE_KEEP_WINDOW,
            resolveImageKeepWindow,
        )

        assert resolveImageKeepWindow("claude-sonnet-4-20250514") == LONG_CONTEXT_IMAGE_KEEP_WINDOW

    def test_ultraLongContextModelWidestWindow(self):
        """1M 档（gemini-1.5-pro）→ 超长上下文档保留窗。"""
        from neurova.context.image_trim_policy import (
            ULTRA_LONG_CONTEXT_IMAGE_KEEP_WINDOW,
            resolveImageKeepWindow,
        )

        assert resolveImageKeepWindow("gemini-1.5-pro") == ULTRA_LONG_CONTEXT_IMAGE_KEEP_WINDOW


# ── 第一档：图像先于文本丢弃 ─────────────────────────────────────

class TestStripImagesOverBudget:
    def test_underBudgetNoop(self):
        from neurova.context.image_trim_policy import stripImagesOverBudget

        msgs = [_textMsg("短文本"), _imgMsg("带图消息")]
        out, stats = stripImagesOverBudget(msgs, budget_tokens=10**9, keep_window=4)
        assert out == msgs, "未超预算必须零行为变化"
        assert stats["images_stripped"] == 0

    def test_noImagesNoopEvenWhenOverBudget(self):
        from neurova.context.image_trim_policy import stripImagesOverBudget

        msgs = [_textMsg("只有文本" * 200)]
        out, stats = stripImagesOverBudget(msgs, budget_tokens=10, keep_window=4)
        assert out == msgs, "无图可裁时原样返回（文本交给第二档折叠）"
        assert stats["images_stripped"] == 0

    def test_stripsOldestImagesFirst_untilBudget(self):
        """超预算 → 从最旧的含图消息起逐条摘图，直至回到预算内。"""
        from neurova.context.image_trim_policy import stripImagesOverBudget

        msgs = [_imgMsg(f"图消息{i}") for i in range(4)]
        meter = WindowTokenMeter()
        total = meter.total(msgs)
        budget = total - 1600  # 需摘 ≥2 张图（每张固定计价 800）才放得下

        out, stats = stripImagesOverBudget(msgs, budget, keep_window=0, meter=meter)

        assert stats["images_stripped"] >= 2, "必须通过摘图回到预算内"
        assert stats["tokens_after"] <= budget, "裁图后窗口必须回到预算内"
        assert stats["tokens_before"] == total
        assert all(not _hasImage(m) for m in out[: stats["images_stripped"]]), \
            "被裁的必须是从最旧起的含图消息"
        assert _placeholderCount(out) == stats["images_stripped"], "被摘图像必须换占位文本"
        # 文本部件永不触碰
        for src, dst in zip(msgs, out):
            src_text = src["content"][0]["text"]
            assert dst["content"][0]["text"] == src_text

    def test_keepWindowProtectsRecentImages(self):
        """只裁旧图：keep 窗内的近期含图消息永不摘（哪怕仍超预算）。"""
        from neurova.context.image_trim_policy import stripImagesOverBudget

        msgs = [_imgMsg(f"图消息{i}") for i in range(4)]
        meter = WindowTokenMeter()
        total = meter.total(msgs)
        budget = total - 1600  # 想摘 2 张，但 keep 窗只放开最旧 2 条

        out, stats = stripImagesOverBudget(msgs, budget, keep_window=2, meter=meter)

        assert stats["images_stripped"] == 2, "只能摘 keep 窗之外的最旧 2 条"
        assert stats["tokens_after"] > budget, "裁不动时诚实停下（不碰文本、不碰近期图）"
        kept = [m for m in out if _hasImage(m)]
        assert len(kept) == 2, "keep 窗内 2 条近期图像必须原样保留"
        assert kept[-1]["content"] == msgs[-1]["content"], "最近一条含图消息逐字节保留"
        assert _placeholderCount(out) == 2

    def test_textNeverTouched(self):
        """图像先于文本丢弃：纯文本轮在任何超预算下都不被本档触碰。"""
        from neurova.context.image_trim_policy import stripImagesOverBudget

        msgs = [_textMsg("纯文本" * 100), _imgMsg("带图"), _textMsg("尾文本" * 100)]
        meter = WindowTokenMeter()
        total = meter.total(msgs)
        budget = total - 500  # 摘 1 张图即够

        out, stats = stripImagesOverBudget(msgs, budget, keep_window=0, meter=meter)

        assert stats["images_stripped"] == 1
        assert out[0]["content"] == msgs[0]["content"], "文本轮原样保留"
        assert out[2]["content"] == msgs[2]["content"], "文本轮原样保留"
        assert stats["tokens_after"] <= budget

    def test_doesNotMutateCallerMessages(self):
        from neurova.context.image_trim_policy import stripImagesOverBudget

        msgs = [_imgMsg("图"), _textMsg("文本")]
        snapshot = copy.deepcopy(msgs)
        stripImagesOverBudget(msgs, budget_tokens=10, keep_window=0)
        assert msgs == snapshot, "不得就地改写调用方消息（与 image_retention 同形）"


# ── compact_window 集成：裁图档先于文本折叠 ─────────────────────

class TestCompactWindowImageTier:
    @pytest.mark.asyncio
    async def test_imagesShedBeforeTextFold(self):
        """旧图摘除即可回到预算 → 零文本折叠（无摘要行、消息一条不折）。"""
        msgs = [_imgMsg(f"早期图片轮{i}") for i in range(4)] + [_textMsg("近期文本" * 100)]
        meter = WindowTokenMeter()
        total = meter.total(msgs)
        budget = total - 1600  # 摘 2 张旧图即够

        compaction = await compact_window(
            msgs, budget, summarize=None, image_keep_window=1, keep_min_messages=1,
        )

        assert compaction is not None, "裁图档生效时必须返回压缩结果（不静默吞掉）"
        assert compaction.summary is None, "未动文本 → 无摘要"
        assert compaction.compacted_count == 0, "零文本折叠"
        assert compaction.images_stripped >= 2, "裁图档必须上报摘图数"
        assert compaction.tokens_before == total and compaction.tokens_after <= budget
        assert len(compaction.window) == len(msgs), "消息条数不变（只换部件，不折消息）"
        assert _placeholderCount(compaction.window) == compaction.images_stripped

    @pytest.mark.asyncio
    async def test_keepWindowRespectedInsideCompaction(self):
        """compact_window 内同样只裁 keep 窗外旧图；裁完仍超 → 文本折叠接手。"""
        msgs = [_imgMsg("旧图0"), _imgMsg("受保护图1"), _textMsg("长文本" * 1000)]
        meter = WindowTokenMeter()
        total = meter.total(msgs)
        budget = total - 900  # 摘 1 张旧图（keep 窗=1 保护最后 1 条含图消息）仍差一点

        compaction = await compact_window(
            msgs, budget, summarize=None, image_keep_window=1, keep_min_messages=2,
        )

        assert compaction is not None
        assert compaction.images_stripped == 1, "keep 窗=1 → 只摘最旧 1 张"
        assert compaction.tokens_after < compaction.tokens_before
        keptWithImage = [m for m in compaction.window if _hasImage(m)]
        assert len(keptWithImage) == 1, "受保护的近期含图消息必须留在窗口"
        assert keptWithImage[0] == msgs[1], "近期图像部件逐字节原样（绝不被摘）"

    @pytest.mark.asyncio
    async def test_defaultNoImageTier_zeroBehaviorChange(self):
        """image_keep_window 缺省（None）→ 不启用裁图档，行为与改前一致。"""
        msgs = [_imgMsg("图0"), _imgMsg("图1"), _imgMsg("图2"), _textMsg("长文本" * 1000)]
        meter = WindowTokenMeter()
        total = meter.total(msgs)
        budget = int(total * 0.5)

        compaction = await compact_window(msgs, budget, summarize=None, keep_min_messages=2)

        assert compaction is not None
        assert compaction.images_stripped == 0, "未启用裁图档 → 零摘图"
        assert compaction.compacted_count == 2, "照旧走整条消息折叠（最旧 2 条）"
        keptWithImage = [m for m in compaction.window if _hasImage(m)]
        assert len(keptWithImage) == 1, "折叠保留区里的图片部件原样保留"
        assert keptWithImage[0] == msgs[2], "保留区含图消息与原消息逐字节一致"
