"""可信轮次来源（TurnOrigin）解析 —— 任务2 actionability 门控的信号地基。

设计（默认即安全）：
- 缺失/非法/未识别 → HUMAN：存疑一律按人类对待，门控永不抑制人类/不明轮次。
- 显式 metadata["turn_origin"] 命中枚举 → 对应源。
- 蜂群既有约定 metadata["source"]=="swarm" → SWARM（无需改 swarm 即可识别）。
- 机器源集合 = {bot_peer, swarm, collaboration, system}；human/unknown 不算机器源。

生产方在各自入口打 turn_origin：channel_router（human/bot_peer）、
swarm（source=swarm 已存在）、协作总线（collaboration）。
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, Optional


class TurnOrigin(str, Enum):
    HUMAN = "human"
    BOT_PEER = "bot_peer"            # 群里其它 bot/agent 发来的消息
    SWARM = "swarm"                  # 蜂群派生的子 Agent 轮次
    COLLABORATION = "collaboration"  # 内部协作总线/agent 通信注入
    SYSTEM = "system"
    UNKNOWN = "unknown"


# 只有明确机器源才可能被抑制；human/unknown 永不。
MACHINE_ORIGINS = frozenset(
    {TurnOrigin.BOT_PEER, TurnOrigin.SWARM, TurnOrigin.COLLABORATION, TurnOrigin.SYSTEM}
)


def resolve_turn_origin(metadata: Optional[Dict[str, Any]]) -> TurnOrigin:
    """从轮次 metadata 解析可信来源；任何不确定都回落到 HUMAN（安全默认）。"""
    if not isinstance(metadata, dict):
        return TurnOrigin.HUMAN

    raw = str(metadata.get("turn_origin") or "").strip().lower()
    if raw:
        try:
            return TurnOrigin(raw)
        except ValueError:
            return TurnOrigin.HUMAN  # 非法值 → 存疑 → 按人类对待

    if str(metadata.get("source") or "").strip().lower() == "swarm":
        return TurnOrigin.SWARM

    return TurnOrigin.HUMAN


def is_machine_origin(origin: TurnOrigin) -> bool:
    return origin in MACHINE_ORIGINS


def is_machine_origin_value(value) -> bool:
    """字符串/None 版机器源判定（供从会话历史读回的原始 origin 直接判定）。

    任何无法识别（None/空/非法）→ False，即"非机器源/存疑"→ 按人类对待（保守放行）。"""
    if not value:
        return False
    try:
        return is_machine_origin(TurnOrigin(str(value).strip().lower()))
    except ValueError:
        return False


__all__ = [
    "TurnOrigin",
    "MACHINE_ORIGINS",
    "resolve_turn_origin",
    "is_machine_origin",
    "is_machine_origin_value",
]
