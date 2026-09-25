"""查询难度 → 思考档位（light/deep）推断（G2 per-turn 自动定档）

设计约束（对齐 AGENTS.md / 修复教义）：
- 纯函数、无 LLM 调用、无外部 I/O：per-turn 零追加成本/时延。
- 保守：只在"强分析信号 / 超长"→ deep、"精确寒暄"→ light 时给出档位；
  歧义一律返回空串（保持现状，不改默认回答风格）。
- 中文优先关键词表（本仓库以中文为主），命中即判定，避免误伤。
- 与 chat_pipeline 的 thinking_effort 机制单一真源：调用方显式档位优先级更高。
"""
from __future__ import annotations

import os
from typing import Tuple

# 触发"深度思考"的强信号关键词（工程/分析/推理类，中文为主）
_DEEP_HINTS: Tuple[str, ...] = (
    "分析", "架构", "评估", "权衡", "取舍", "对比", "比较", "论证", "证明",
    "推理", "推导", "调试", "排查", "根因", "优化", "重构", "方案", "规划",
    "设计", "原理", "性能", "并发", "算法", "迁移", "升级", "审计", "瓶颈",
    "为什么", "如何实现", "怎么实现", "一步步", "多步骤", "可行性",
)

# 触发"简洁速答"的精确寒暄/致谢（整句命中才算，避免误伤含寒暄的实质问题）
_LIGHT_EXACT: frozenset = frozenset({
    "你好", "您好", "hi", "hello", "在吗", "在么", "在不在",
    "谢谢", "多谢", "感谢", "辛苦", "好的", "收到", "ok", "行",
    "早上好", "中午好", "晚上好", "哈哈", "嗯", "哦",
})

# 超长即判定为深度（复杂诉求通常伴随长描述）
_DEEP_LEN = 120


def infer_query_effort(text: str) -> str:
    """从查询文本推断思考档位。

    Returns:
        "deep" — 强分析/超长诉求；
        "light" — 纯寒暄/致谢；
        ""      — 歧义，保持现状（不注入任何回答模式指令）。
    """
    t = (text or "").strip()
    if not t:
        return ""
    low = t.lower()

    if len(t) >= _DEEP_LEN or any(k in low for k in _DEEP_HINTS):
        return "deep"
    if low in _LIGHT_EXACT:
        return "light"
    return ""


def auto_effort_enabled() -> bool:
    """自动定档总开关（kill-switch）：NEUROVA_AUTO_EFFORT=off 关闭，默认开启。"""
    return (os.environ.get("NEUROVA_AUTO_EFFORT") or "on").strip().lower() != "off"


__all__ = ["infer_query_effort", "auto_effort_enabled"]
