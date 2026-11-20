# -*- coding: utf-8 -*-
"""动机调制的主动提问出队节奏 + 管线旁路判定小助手（自 post_chat_pipeline 抽出）。

动机账本（MotivationLedger）的 purpose/autonomy 强度等权混合后，按档位给出
主动提问的**最小全局出队间隔**：强度低 → 频率上限收紧；强度高 → 不额外限流
（维持既有行为，每问冷却仍由 QuestionQueueManager 自己管）。只调出队频率，
不新造行为通道、不改提问内容生成。档位阈值/间隔均为具名常量，可测可注入；
强度经 ledger.snapshot() 既有口径读取，不另起第二套算法。

`post_chat_pipeline` 仍再出口这些名字（orchestrator 与测试的导入面不变）。
"""

from __future__ import annotations

from neurova.core.logger import get_logger

logger = get_logger(__name__)

MOTIVATION_QUESTION_INTENSITY_HIGH = 0.45  # purpose/autonomy 均值 ≥ 此值视为高动机
MOTIVATION_QUESTION_INTENSITY_LOW = 0.3  # 均值 < 此值视为低动机
# 阈值依据：生产信号面下 purpose 上限 0.4（values/goals 暂无写入路径，仅贡献回流）、
# autonomy 上限 0.58（freedom 恒 0.5，提问满意度 0.7），均值天花板 0.49——
# HIGH 取 0.45 保证档位在生产可达，不造"永不命中"的死档。
MOTIVATION_QUESTION_MIN_INTERVAL_HIGH_S = 0.0  # 高动机：不额外限流
MOTIVATION_QUESTION_MIN_INTERVAL_MID_S = 900.0  # 中动机：15 分钟至多一问
MOTIVATION_QUESTION_MIN_INTERVAL_LOW_S = 1800.0  # 低动机：30 分钟至多一问
MOTIVATION_QUESTION_INTERVAL_TABLE = (
    # (强度下限, 最小出队间隔秒) —— 自高到低首档命中即返回
    (MOTIVATION_QUESTION_INTENSITY_HIGH, MOTIVATION_QUESTION_MIN_INTERVAL_HIGH_S),
    (MOTIVATION_QUESTION_INTENSITY_LOW, MOTIVATION_QUESTION_MIN_INTERVAL_MID_S),
    (0.0, MOTIVATION_QUESTION_MIN_INTERVAL_LOW_S),
)


def resolveMotivationQuestionInterval(intensity: float) -> float:
    """按动机强度查主动提问最小出队间隔（秒）：强度越低间隔越长。"""
    for threshold, interval in MOTIVATION_QUESTION_INTERVAL_TABLE:
        if intensity >= threshold:
            return interval
    return MOTIVATION_QUESTION_MIN_INTERVAL_LOW_S


def isMetaRetrievalTool(tool_name: str) -> bool:
    """元检索工具判定（**单一 import 点**，名单本体在 `tool_layers/capability_graph`）。

    本包装只为让"撤掉反哺禁令 ⇒ 故障复现"这条反向锁可被单独观测
    （教义第 1 条判据）；判定口径本身不在这里定义，不构成第二份名单。
    """
    from neurova.tool_layers.capability_graph import is_meta_retrieval_tool

    return is_meta_retrieval_tool(tool_name)


def noteRewardGuardSkip(tool_name: str, channel: str) -> None:
    """反哺/发布禁令命中的观测写入（失败不阻断主链）。"""
    try:
        from neurova.tool_layers.capability_graph import noteMetaRewardSkip

        noteMetaRewardSkip(tool_name, channel)
    except Exception:  # noqa: BLE001 - 观测缺失不得让后处理步骤整体失败
        logger.debug("反哺禁令计数写入失败", exc_info=True)


def rsiBackoffEveryTurns() -> int:
    """RSI 降频巡检窗口（工单 008）：收敛或度量失明时，每 N 轮仍跑一次。

    §6-3 收口（2026-10-06）：原硬编码 20 与收敛窗口（convergence_analyzer.
    window_size 默认 20）同量级——一个窗口的证据过期之后就重新量一次，
    而不是永久停机。N 现从 evolution_settings.rsi_backoff_every_turns 读
    （默认仍是 20）。仅在 backoff 分支被求值（or 短路），常态零开销。
    """
    from neurova.evolution.evolution_settings import load_settings

    return max(1, int(load_settings().rsi_backoff_every_turns))
