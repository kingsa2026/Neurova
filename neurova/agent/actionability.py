"""actionability 门控决策 —— 任务2（保守、机器源限定）。

纯函数、无 IO：便于单测，也把"判定逻辑"与"开关来源/会话回看"解耦。
调用方（chat_pipeline._check_actionability）负责注入 enabled（来自系统设置
"LLM 路由"分区，默认关）与 human_recent（会话近期是否有人类介入）。

安全原则：只有在"门控开启 + 明确机器源 + 近期无人类"三者同时成立时才判不可行；
其余（尤其人类/存疑/信息缺失）一律可行，绝不误吞人类消息。
"""
from __future__ import annotations

import os
from typing import Optional, Tuple

from pathlib import Path

from neurova.agent.turn_origin import TurnOrigin, is_machine_origin


def evaluate_actionability(
    enabled: bool, origin: TurnOrigin, human_recent: bool
) -> Tuple[bool, str]:
    """返回 (actionable, reason)。

    actionable=True 时 reason 为空串；False 时 reason 为可诊断的机读标签。
    """
    if not enabled:
        return True, ""
    if not is_machine_origin(origin):  # human / unknown → 永不抑制
        return True, ""
    if human_recent:                   # 机器源但近期有人类介入 → 放行
        return True, ""
    return False, "machine_origin_no_recent_human"


def get_actionability_config(path: "Optional[Path]" = None) -> Tuple[bool, int]:
    """读门控参数：优先系统设置"LLM 路由"分区（可持久化、管理页可控），
    env 显式值作为运维逃生门（最优先）。默认全关（零行为漂移）。

    Returns:
        (enabled, lookback)
    """
    try:
        from neurova.core.app_settings import load_app_settings

        routing = load_app_settings(path).get("routing") or {}
    except Exception:  # noqa: BLE001 - 读设置失败不阻断（回落默认关）
        routing = {}

    enabled = bool(routing.get("actionability_enabled", False))
    try:
        lookback = int(routing.get("actionability_lookback", 20) or 20)
    except (TypeError, ValueError):
        lookback = 20

    env = (os.environ.get("NEUROVA_ACTIONABILITY_GATE") or "").strip().lower()
    if env in ("on", "1", "true", "yes"):
        enabled = True
    elif env in ("off", "0", "false", "no"):
        enabled = False
    lb_env = (os.environ.get("NEUROVA_ACTIONABILITY_LOOKBACK") or "").strip()
    if lb_env.isdigit():
        lookback = int(lb_env)
    return enabled, lookback


__all__ = ["evaluate_actionability", "get_actionability_config"]
