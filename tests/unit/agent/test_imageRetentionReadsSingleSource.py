# -*- coding: utf-8 -*-
"""卡 L1（多模态追平批二遗留）：chat_pipeline 的历史图片保留窗口收口到单源。

现状（红灯）：`ChatPipeline._IMAGE_RETENTION_KEEP_LAST = 4` 是与
`model_limits.MULTIMODAL_IMAGE_RETAIN_PER_TURN` 同值的第二份字面量——
单源改值时管线侧保留窗口不随动，口径分叉（同根因第 4 处命中点）。

判据（红→绿）：
1. 行为：monkeypatch 单源为 2，走 `_apply_image_retention` 真实保留路径，
   保留数必须随单源变（字面量恒 4 → 红）；
2. 同源锁约：chat_pipeline 源内不再有该字面量。
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest

from neurova.agent.chat_pipeline import ChatPipeline
from neurova.llm import model_limits


def _imageMsg(text: str) -> dict:
    return {
        "role": "user",
        "content": [
            {"type": "text", "text": text},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
        ],
    }


def _pipeline() -> ChatPipeline:
    # 最小替身：_apply_image_retention 只读 ctx.context，不依赖完整装配
    return object.__new__(ChatPipeline)


class TestImageRetentionReadsSingleSource:
    def test_retentionWindowFollowsSingleSource(self, monkeypatch):
        """单源改成 2 → 管线保留路径只留最近 2 轮图片（字面量恒 4 时必红）。"""
        monkeypatch.setattr(model_limits, "MULTIMODAL_IMAGE_RETAIN_PER_TURN", 2)
        ctx = SimpleNamespace(context=[_imageMsg(f"轮{i}") for i in range(6)])

        _pipeline()._apply_image_retention(ctx)

        kept = [
            msg for msg in ctx.context
            if any(
                isinstance(p, dict) and p.get("type") == "image_url"
                for p in msg["content"]
            )
        ]
        placeholders = [
            p for msg in ctx.context for p in msg["content"]
            if isinstance(p, dict) and p.get("type") == "text" and "已省略" in str(p.get("text"))
        ]
        assert len(kept) == 2, f"单源=2 时应只保留最近 2 轮图片，实际保留 {len(kept)} 轮"
        assert len(placeholders) == 4, f"其余 4 轮图片应置占位文本，实际 {len(placeholders)} 处"

    def test_retentionWindowFollowsSingleSource_atFour(self, monkeypatch):
        """单源为 4 时行为与收拢前一致（6 轮含图 → 留 4 摘 2），防矫枉过正。"""
        monkeypatch.setattr(model_limits, "MULTIMODAL_IMAGE_RETAIN_PER_TURN", 4)
        ctx = SimpleNamespace(context=[_imageMsg(f"轮{i}") for i in range(6)])

        _pipeline()._apply_image_retention(ctx)

        kept = [
            msg for msg in ctx.context
            if any(
                isinstance(p, dict) and p.get("type") == "image_url"
                for p in msg["content"]
            )
        ]
        assert len(kept) == 4, f"单源=4 时应保留 4 轮图片，实际 {len(kept)} 轮"

    def test_chatPipelineHasNoSecondKeepLastLiteral(self):
        """同源锁约：chat_pipeline 源内不再允许 `_IMAGE_RETENTION_KEEP_LAST` 字面量。"""
        source = inspect.getsource(ChatPipeline)
        assert "_IMAGE_RETENTION_KEEP_LAST" not in source, (
            "keep_last 必须调用时读 model_limits.MULTIMODAL_IMAGE_RETAIN_PER_TURN 单源，"
            "不得在 chat_pipeline 里留第二份字面量"
        )
        assert not hasattr(ChatPipeline, "_IMAGE_RETENTION_KEEP_LAST")
