# -*- coding: utf-8 -*-
"""P2-6 工具轮 reasoning 回放。

机制就绪、**默认关闭**（NEUROVA_REASONING_REPLAY=1 显式开启）：
- DeepSeek reasoner 等提供方显式禁止把 reasoning_content 回传（会 400），
  盲目回放对多 provider 兼容面是回归风险（增量不下降约束）
- 开启时仍受能力门约束：仅 llm_router._infer_capabilities 标记 REASONING
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

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


def build_reasoning_assistant_message(
    reasoning_text: str,
    round_reply: str = "",
    tool_calls: Optional[List[Any]] = None,
) -> Dict[str, Any]:
    """构造携带推理链的 assistant 消息（OpenAI 兼容扩展字段形态）。

    tool_calls 对象按 (id, name, arguments) 投影为协议形态；入参异常时
    降级为纯文本 assistant 消息。
    """
    message: Dict[str, Any] = {
        "role": "assistant",
        "content": str(round_reply or ""),
        "reasoning_content": str(reasoning_text or ""),
    }
    if tool_calls:
        try:
            message["tool_calls"] = [
                {
                    "id": getattr(tc, "id", None) or f"call_{i}",
                    "type": "function",
                    "function": {
                        "name": getattr(getattr(tc, "function", None), "name", "") or "",
                        "arguments": getattr(getattr(tc, "function", None), "arguments", "") or "{}",
                    },
                }
                for i, tc in enumerate(tool_calls)
            ]
        except Exception:  # noqa: BLE001
            pass
    return message
