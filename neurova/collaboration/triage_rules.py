"""SB-1 确定性分诊规则裁决器（纯函数规则层）。

出处：docs/04-plans/2026-11-22-small-brain-triage-gate-wiring-plan.md
§4「确定性规则层（SB-1）」与 §8 拆卡 SB-1。R0-R4 判定与阈值
（近 10 条有人类 / 5 分钟内有人类活动 / ≥20 条独走 / 近 6 条内重复 ≥3 次 /
相似度 0.9）均取原分诊门自述值（neurova/llm/triage.py:87-115 的原则与
SIGNALS 描述），本模块只做机械判定，不发明新口径。

设计要点（计划文档 §4）：
- 无状态纯函数：不维护跨轮计数、不需要 TTL；同输入同输出（确定性，
  禁随机、禁 built-in hash()）；人类消息一进窗口结论自动翻转；
- 本模块是 SB-2 微型判定模型的特征单源，特征口径由
  TRIAGE_FEATURE_VERSION 标记；
- 仅依赖标准库；时间解析用 datetime.fromisoformat（Python 3.12 支持
  ISO8601），个别不可解析的时间戳只跳过该条的时间计算，不让整窗失败。

事件形态（输入，来自 SessionSyncManager.get_messages，按时间升序）：
    {"role": "user" | "assistant", "content": str, "timestamp": ISO8601 str, ...}
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List

# --- 特征与阈值常量（阈值 = 原分诊门自述值，triage.py:87-115） ---

TRIAGE_FEATURE_VERSION = "triage-features-v2"

HUMAN_WINDOW_EVENTS = 10
HUMAN_WINDOW_SECONDS = 300.0
AGENT_LOOP_THRESHOLD = 20
REPETITION_WINDOW = 6
REPETITION_MIN_DUPLICATES = 3
REPETITION_MIN_LENGTH = 8
SIMILARITY_THRESHOLD = 0.9
MAX_WINDOW = 50

_QUESTION_MARKERS = ("?", "？", "吗", "么")

# --- v2 语义标记词库（内容子串，casefold 匹配；确定性） ---
# 产出物标记：消息里带这些词 → 大概率有实质交付，不宜静默跳过
_DELIVERABLE_MARKERS = (
    "已完成", "结果如下", "总结", "报告", "产出", "如下", "清单", "方案",
    "已修复", "已部署", "已发布", "已上线", "验收", "```", "http",
    "completed", "summary", "result", "deployed", "fixed", "https",
)
# 请求人类决策标记：向人要结论/回复 → 应放行
_DECISION_MARKERS = (
    "请确认", "请审批", "需要确认", "是否继续", "是否需要", "拍板", "请示",
    "待确认", "等待确认", "请回复", "请指示", "请批", "麻烦", "@",
    "please confirm", "need approval", "awaiting",
)
# 风险/故障标记：出状况 → 人应当知情
_RISK_MARKERS = (
    "失败", "报错", "异常", "错误", "阻塞", "卡住", "超时", "回滚", "事故",
    "无法", "拒绝", "告警", "critical", "error", "fail", "exception", "timeout",
)


@dataclass(frozen=True)
class TriageVerdict:
    """分诊裁决结论。

    action: "allow"（放行）| "skip"（跳过本轮）
    reason: no_events / human_last / human_in_window /
            agent_loop_no_human / verbatim_loop / default_allow
    features: 本轮特征向量（extractTriageFeatures 输出，供 SB-2 消费）
    """

    action: str
    reason: str
    features: Dict[str, float]


def _normalizeText(text: str) -> str:
    """归一化文本：casefold + 去标点（保留字母数字与空白）+ 压缩空白。

    出处：计划文档 §4 R3「归一化（casefold+去标点空白，长度≥8）」。
    """
    lowered = text.casefold()
    kept = "".join(ch for ch in lowered if ch.isalnum() or ch.isspace())
    return " ".join(kept.split())


def _parseTimestamp(value) -> datetime | None:
    """解析 ISO8601 时间戳；不可解析返回 None（调用方跳过该条时间计算）。"""
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _contentOf(event: Dict) -> str:
    """取事件文本；非字符串按空串处理（不让脏数据炸掉整窗计算）。"""
    content = event.get("content")
    return content if isinstance(content, str) else ""


def extractTriageFeatures(events: List[Dict], currentInput: str = "") -> Dict[str, float]:
    """从会话窗口提取分诊特征（固定 15 键，值全为 float）。

    v2 = v1 的 11 个结构特征 + 4 个内容语义特征（产出物/决策请求/风险
    标记比例与内容多样性），词库子串匹配，确定性。

    出处：计划文档 §4/§5.2——R1-R3 的连续化特征，规则层与 SB-2 模型
    共用同一份（特征单源）。窗口取末尾 MAX_WINDOW(50) 条；缺数据时取值
    固定：无人类消息或所需时间戳不可解析 → humanEventDistance /
    humanTimeDistanceSec = -1.0；assistant 不足 3 条或无合格复读文本 →
    maxRepeatCount = 1.0；currentInput 为空/归一化后不足 8 字符或无合格
    比对文本 → maxSimilarity = 0.0；可解析时间戳不足 2 条 →
    messageRatePerMin = 0.0；无 assistant → 长度统计 0.0；空窗口 →
    questionRatio = 0.0。
    """
    window = list(events)[-MAX_WINDOW:] if events else []
    features: Dict[str, float] = {}

    # 人类消息定位：事件距离（窗口末尾到最近一条 user 消息）与时间距离
    latestUserIndex = None
    for idx in range(len(window) - 1, -1, -1):
        if window[idx].get("role") == "user":
            latestUserIndex = idx
            break
    if latestUserIndex is None:
        features["humanEventDistance"] = -1.0
        features["humanTimeDistanceSec"] = -1.0
    else:
        features["humanEventDistance"] = float(len(window) - 1 - latestUserIndex)
        latestTs = _parseTimestamp(window[-1].get("timestamp"))
        humanTs = _parseTimestamp(window[latestUserIndex].get("timestamp"))
        if latestTs is None or humanTs is None:
            features["humanTimeDistanceSec"] = -1.0
        else:
            features["humanTimeDistanceSec"] = (latestTs - humanTs).total_seconds()

    # agent 独走长度：窗口末尾起连续 assistant 消息条数
    agentStreak = 0
    for idx in range(len(window) - 1, -1, -1):
        if window[idx].get("role") == "assistant":
            agentStreak += 1
        else:
            break
    features["agentStreakLength"] = float(agentStreak)

    # 计数与长度统计
    userCount = sum(1 for e in window if e.get("role") == "user")
    assistantEvents = [e for e in window if e.get("role") == "assistant"]
    features["userCount"] = float(userCount)
    features["assistantCount"] = float(len(assistantEvents))
    if assistantEvents:
        assistantLengths = [len(_contentOf(e)) for e in assistantEvents]
        features["meanAssistantLength"] = sum(assistantLengths) / len(assistantLengths)
        features["maxAssistantLength"] = float(max(assistantLengths))
    else:
        features["meanAssistantLength"] = 0.0
        features["maxAssistantLength"] = 0.0

    # 复读检测：最近 6 条 assistant 消息，归一化后长度≥8 才参与计数
    recentAssistant = assistantEvents[-REPETITION_WINDOW:]
    if len(assistantEvents) < REPETITION_MIN_DUPLICATES:
        features["maxRepeatCount"] = 1.0
    else:
        repeatCounts: Dict[str, int] = {}
        for e in recentAssistant:
            normalized = _normalizeText(_contentOf(e))
            if len(normalized) < REPETITION_MIN_LENGTH:
                continue
            repeatCounts[normalized] = repeatCounts.get(normalized, 0) + 1
        features["maxRepeatCount"] = float(max(repeatCounts.values())) if repeatCounts else 1.0

    # 相似度：本回合输入 vs 最近 6 条 assistant 消息的最大 SequenceMatcher.ratio
    normalizedInput = _normalizeText(currentInput)
    if len(normalizedInput) < REPETITION_MIN_LENGTH:
        features["maxSimilarity"] = 0.0
    else:
        bestRatio = 0.0
        for e in recentAssistant:
            normalized = _normalizeText(_contentOf(e))
            if len(normalized) < REPETITION_MIN_LENGTH:
                continue
            ratio = difflib.SequenceMatcher(None, normalizedInput, normalized).ratio()
            if ratio > bestRatio:
                bestRatio = ratio
        features["maxSimilarity"] = bestRatio

    # 消息速率：条数 / max(时间跨度分钟, 1.0)；可解析时间戳不足 2 条为 0
    parseableTimes = []
    for e in window:
        ts = _parseTimestamp(e.get("timestamp"))
        if ts is not None:
            parseableTimes.append(ts)
    if len(parseableTimes) < 2:
        features["messageRatePerMin"] = 0.0
    else:
        spanMinutes = (max(parseableTimes) - min(parseableTimes)).total_seconds() / 60.0
        features["messageRatePerMin"] = len(window) / max(spanMinutes, 1.0)

    # 疑问句比例：最近 10 条消息中含 ?/？/吗/么 的比例
    recentWindow = window[-10:]
    if recentWindow:
        questionCount = sum(
            1 for e in recentWindow if any(marker in _contentOf(e) for marker in _QUESTION_MARKERS)
        )
        features["questionRatio"] = questionCount / len(recentWindow)
    else:
        features["questionRatio"] = 0.0

    # v2 语义特征：最近 10 条 assistant 消息的内容标记比例 + 内容多样性。
    # 动机（v1→v2 升级）：结构特征分不清「有实质产出/需人决策的独走」与
    # 「纯台账空转」，是误杀前沿的瓶颈（见计划 §5.2 特征语义化）。
    semanticTexts = [
        _contentOf(e).casefold() for e in window[-10:] if e.get("role") == "assistant"
    ]

    def _markerRatio(markers) -> float:
        if not semanticTexts:
            return 0.0
        hits = sum(1 for text in semanticTexts if any(marker in text for marker in markers))
        return hits / len(semanticTexts)

    features["deliverableMarkerRatio"] = _markerRatio(_DELIVERABLE_MARKERS)
    features["decisionRequestRatio"] = _markerRatio(_DECISION_MARKERS)
    features["riskMarkerRatio"] = _markerRatio(_RISK_MARKERS)

    diversityPrefixes = set()
    for text in semanticTexts:
        normalized = _normalizeText(text)
        if len(normalized) >= REPETITION_MIN_LENGTH:
            diversityPrefixes.add(normalized[:16])
    features["contentDiversityRatio"] = (
        len(diversityPrefixes) / len(semanticTexts) if semanticTexts else 0.0
    )

    return features


def evaluateTriage(events: List[Dict], currentInput: str = "") -> TriageVerdict:
    """按 R0-R4 顺序短路裁决（出处：计划文档 §4 规则表）。

    - R0：窗口为空 → allow/no_events；最后一条是人类消息 → allow/human_last
    - R1：0 ≤ humanEventDistance ≤ 10 或 0 ≤ humanTimeDistanceSec ≤ 300
      → allow/human_in_window（人类在场/刚活动，零计算快路径之后的保守放行）
    - R2：agentStreakLength ≥ 20 → skip/agent_loop_no_human（独走环）
    - R3：maxRepeatCount ≥ 3 或 maxSimilarity ≥ 0.9 → skip/verbatim_loop（复读环）
    - R4：以上皆不命中 → allow/default_allow（保守弃权，与原门
      "拿不准→响应"同构）
    """
    features = extractTriageFeatures(events, currentInput)

    if not events:
        return TriageVerdict("allow", "no_events", features)
    if features["humanEventDistance"] == 0.0:
        return TriageVerdict("allow", "human_last", features)
    if (0.0 <= features["humanEventDistance"] <= HUMAN_WINDOW_EVENTS) or (
        0.0 <= features["humanTimeDistanceSec"] <= HUMAN_WINDOW_SECONDS
    ):
        return TriageVerdict("allow", "human_in_window", features)
    if features["agentStreakLength"] >= AGENT_LOOP_THRESHOLD:
        return TriageVerdict("skip", "agent_loop_no_human", features)
    if (
        features["maxRepeatCount"] >= REPETITION_MIN_DUPLICATES
        or features["maxSimilarity"] >= SIMILARITY_THRESHOLD
    ):
        return TriageVerdict("skip", "verbatim_loop", features)
    return TriageVerdict("allow", "default_allow", features)
