# -*- coding: utf-8 -*-
"""P2-6 工具轮 reasoning 回放闸门。

机制就绪、**默认关闭**（NEUROVA_REASONING_REPLAY=1 显式开启）：
- DeepSeek reasoner 等提供方显式禁止把 reasoning_content 回传（会 400），
  盲目回放对多 provider 兼容面是回归风险（增量不下降约束）
- 开启时仍受能力门约束：仅 llm_router._infer_capabilities 标记 REASONING

回放消息本身由 BaseAgentLoop.buildToolRoundMessages 单点构造——tool_calls
声明是无条件的协议要求，reasoning_content 才是本闸门管的可选附加项。
"""
from __future__ import annotations

from neurova.core.logger import get_logger

logger = get_logger(__name__)


def should_replay_reasoning(model_name: str) -> bool:
    """回放闸门：env 开关（默认关）+ 模型能力门（REASONING 标记）。"""
    import os

    if os.environ.get("NEUROVA_REASONING_REPLAY", "0") != "1":
        return False
    try:
        from neurova.llm.llm_router import ModelCapability, _infer_capabilities

        return ModelCapability.REASONING in _infer_capabilities(str(model_name or ""))
    except Exception:  # noqa: BLE001 - 能力查询失败按不回放
        return False
