# -*- coding: utf-8 -*-
"""错误分类只许有一处实现；legacy 流式读取器已整体退役。

`_raise_for_llm_error_dict`（管线侧）与 `BaseAgentLoop._raise_for_error_dict`
（环侧）本是同一件事的两份：同一张五类键表、同一套消息兜底、只是文案与兜底
类型略有出入。两份并存的结果是「同一条上游错误，走环路被判成可重试、
走 legacy 路被判成不可重试」——供应商错误守卫据此决定要不要 fallback，
于是同一份坏配置在两路上表现不同。

判据（S7 批修订）：legacy 读取器（`neurova/agent/legacy_stream_reader.py`）已按 P1-12
整体退役（生产零消费），"两路一致"判据随之了结；本档改钉两件事——

1. 分类实现全仓只剩环侧一处（管线不得再留第二份）；
2. legacy 读取器不回树（谁把第二份分类实现连着读取器复制回来，这里当场红）。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from neurova.agent.chat_pipeline import ChatPipeline
from neurova.agent.loops.base import BaseAgentLoop

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def testPipelineHoldsNoSecondClassifier():
    """管线不得再留一份分类实现（同一件事两个事实源）。"""
    assert not hasattr(ChatPipeline, "_raise_for_llm_error_dict")
    assert callable(BaseAgentLoop._raise_for_error_dict)


def testLegacyStreamReaderStayRetired():
    """legacy 流式读取器已退役（P1-12）——分类职责只认环侧一处，不许连体复活。"""
    assert not (PROJECT_ROOT / "neurova" / "agent" / "legacy_stream_reader.py").exists(), (
        "legacy_stream_reader.py 已按 P1-12 整体退役（生产零消费、错误分类已收敛到 "
        "BaseAgentLoop._raise_for_error_dict 一处）——不许回树")
