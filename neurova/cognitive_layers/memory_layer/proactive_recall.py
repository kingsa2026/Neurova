"""主动回忆机制 — 定时回忆巩固 + 上下文触发回忆 + 任务驱动回忆

设计稿：``docs/01-architecture/14-proactive-recall-mechanism.md``（落地其可验证子集）。

单一事实源纪律：
- 升温/刷新走 ``MemoryManager.markSimulatedRecall`` 单点（温度封顶、
  ``last_accessed_at`` 刷新只此一处）；
- 遗忘优先级复用 ``TemperatureEngine.calculate_forgetting_probability``
  （此前全仓零消费，本模块是其第一个读方）；
- 全部阈值入 memory-settings 的 ``PARAM_SCHEMAS``（``proactive_recall.*``）。

触发方式（2026-11-20 拍板）：定时巩固挂在睡眠周期尾部——
``core/idle_tracker.py`` 巩固链尾与 ``agent_shutdown.py`` 关机整理尾各接一次；
上下文触发接 ``context/injector.py`` 的记忆检索；任务驱动接 swarm 派活任务书拼装。
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

#: 定时巩固/上下文触发的单轮扫描上限（有界，仿 promotion/decay 的游标纪律；
#: 不做全库无界遍历）。
_SCAN_LIMIT = 1000

#: 任务驱动回忆的桶映射。本仓 ``MemoryCategory`` 枚举没有设计稿的
# LESSON/SKILL/RELATIONSHIP，按现役枚举对齐：教训→REFLECTION、
# 技能→TOOL_USAGE、人物/偏好→USER_PREFERENCE。
TASK_CATEGORY_BUCKETS: List[Tuple[str, str]] = [
    ("experiences", "experience"),
    ("lessons", "reflection"),
    ("skills", "tool_usage"),
    ("preferences", "user_preference"),
]

#: 任务关键词切分的分隔符（空格与常见中英文标点）。
_TASK_TOKEN_SPLIT = re.compile(r"[\s,，。;；、:：!！?？()\[\]{}\"'`·…—]+")

#: 关键词最短长度（设计稿 min_keyword_length=2 的对应口径）。
_MIN_TOKEN_LEN = 2


def _utcNow() -> datetime:
    return datetime.now(timezone.utc)


def _asAware(moment: datetime) -> datetime:
    """naive 时间按 UTC 处理（与持久化层的 aware isoformat 对齐）。"""
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment


def _lastTouchedAt(mem: Any) -> datetime:
    """参与闲置判定的时点：``last_accessed_at`` 优先，从未访问退 ``created_at``。"""
    return _asAware(mem.last_accessed_at or mem.created_at)


def _isRecallable(mem: Any) -> bool:
    """结晶（永久）与已遗忘记忆不进主动回忆。"""
    from neurova.cognitive_layers.memory_layer.models import LifecycleStage

    return mem.lifecycle_stage not in (LifecycleStage.CRYSTALLIZED, LifecycleStage.FORGOTTEN)


def _timePatternMatches(pattern: Dict[str, Any], moment: datetime) -> bool:
    """时间模式匹配（设计稿 §2.1）：小时 ±2 窗口 + 星期对齐，任一命中即可。"""
    pattern_hour = pattern.get("hour")
    pattern_weekday = pattern.get("day_of_week")
    if pattern_hour is not None:
        try:
            if abs(int(pattern_hour) - moment.hour) > 2:
                return False
        except (TypeError, ValueError):
            return False
    if pattern_weekday is not None:
        try:
            if int(pattern_weekday) != moment.weekday():
                return False
        except (TypeError, ValueError):
            return False
    return pattern_hour is not None or pattern_weekday is not None


def _proactiveEnabled() -> bool:
    from neurova.cognitive_layers.memory_layer.settings_config import get_memory_settings

    return bool(get_memory_settings().get("proactive_recall.enabled", True))


def runScheduledRecallCycle(
    memory_manager,
    max_memories: int = 100,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """定时回忆巩固：扫描久未访问的未结晶记忆，按遗忘概率降序模拟回忆。

    闲置阈值：重要记忆（``metadata.is_important``）默认 3 天、普通记忆默认
    7 天，可经 ``proactive_recall.important_interval_days`` /
    ``proactive_recall.normal_interval_days`` 调整；升温暖存量
    ``proactive_recall.temperature_boost``（默认 5.0，k=boost/50=0.1，
    弱于真实召回记账 creditRecallHits 的 k=0.25）。

    Returns:
        ``{"recalled_count", "recalled_ids", "candidate_count", "skipped"?}``
    """
    from neurova.cognitive_layers.memory_layer.settings_config import get_memory_settings
    from neurova.cognitive_layers.memory_layer.temperature import TemperatureEngine

    if not _proactiveEnabled():
        return {"recalled_count": 0, "recalled_ids": [], "candidate_count": 0, "skipped": "disabled"}

    cfg = get_memory_settings()
    boost = float(cfg.get("proactive_recall.temperature_boost", 5.0))
    important_days = float(cfg.get("proactive_recall.important_interval_days", 3))
    normal_days = float(cfg.get("proactive_recall.normal_interval_days", 7))
    moment = _asAware(now) if now is not None else _utcNow()

    candidates: List[Tuple[float, Any]] = []
    for mem in memory_manager.iterBodyMemories(limit=_SCAN_LIMIT):
        if not _isRecallable(mem):
            continue
        idle_days = max(0.0, (moment - _lastTouchedAt(mem)).total_seconds() / 86400.0)
        important = bool((mem.metadata or {}).get("is_important", False))
        threshold_days = important_days if important else normal_days
        if idle_days < threshold_days:
            continue
        probability = TemperatureEngine.calculate_forgetting_probability(
            temperature=mem.temperature,
            days_idle=idle_days,
            importance=(mem.importance or 0.0) / 100.0,
        )
        candidates.append((probability, mem))

    candidates.sort(key=lambda pair: (-pair[0], pair[1].id))
    recalled_ids: List[str] = []
    for _probability, mem in candidates[: max(0, int(max_memories))]:
        if memory_manager.markSimulatedRecall(mem.id, boost=boost):
            recalled_ids.append(mem.id)

    result = {
        "recalled_count": len(recalled_ids),
        "recalled_ids": recalled_ids,
        "candidate_count": len(candidates),
    }
    if recalled_ids:
        logger.info("定时回忆巩固: 候选 %d 条，本轮模拟回忆 %d 条", len(candidates), len(recalled_ids))
    return result


def contextTriggeredRecall(
    memory_manager,
    currentTime: Optional[datetime] = None,
    emotionProvider: Optional[Callable[[], tuple]] = None,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """上下文触发回忆：时间模式 + 情感共鸣主动带出，去重限量。

    - 时间触发：``metadata.time_pattern``（``{"hour": 9}`` / ``{"day_of_week": 0}``）
      按小时 ±2 窗口与星期对齐匹配当前时刻；
    - 情感触发：``emotionProvider()`` 返回 ``(emotion, intensity)``，强度达到
      ``proactive_recall.emotion_min_intensity``（默认 0.5）时带出同情感记忆；
    - 单轮带出上限 ``proactive_recall.max_context_recall``（默认 10），
      同温取先到，整体按温度降序。

    Returns:
        ``Memory.to_dict()`` 列表（键含 id/content/temperature/metadata 等）。
    """
    from neurova.cognitive_layers.memory_layer.settings_config import get_memory_settings

    if not _proactiveEnabled():
        return []
    cfg = get_memory_settings()
    max_count = int(limit) if limit is not None else int(cfg.get("proactive_recall.max_context_recall", 10))
    emotion_min = float(cfg.get("proactive_recall.emotion_min_intensity", 0.5))
    moment = _asAware(currentTime) if currentTime is not None else _utcNow()

    target_emotion: Optional[str] = None
    if emotionProvider is not None:
        try:
            emotion = emotionProvider()
        except Exception as exc:  # noqa: BLE001 — 情感源故障不阻断触发回忆
            logger.debug("emotionProvider 失败，跳过情感触发: %s", exc)
            emotion = None
        if emotion:
            raw_type, intensity = emotion[0], float(emotion[1])
            if intensity >= emotion_min:
                target_emotion = str(getattr(raw_type, "value", raw_type))

    recalled: List[Any] = []
    seen: set = set()

    def _push(mem: Any) -> None:
        if mem.id in seen:
            return
        seen.add(mem.id)
        recalled.append(mem)

    for mem in memory_manager.iterBodyMemories(limit=_SCAN_LIMIT):
        if not _isRecallable(mem):
            continue
        pattern = (mem.metadata or {}).get("time_pattern")
        if isinstance(pattern, dict) and _timePatternMatches(pattern, moment):
            _push(mem)
            continue
        if target_emotion is not None and str(getattr(mem.emotion, "value", mem.emotion)) == target_emotion:
            _push(mem)

    recalled.sort(key=lambda m: -m.temperature)
    return [m.to_dict() for m in recalled[: max(0, max_count)]]


def _taskTokens(taskDescription: str) -> List[str]:
    """任务描述切词：按空白与中英文标点切分，滤掉长度 <2 的碎片。"""
    tokens = [
        token.strip()
        for token in _TASK_TOKEN_SPLIT.split(str(taskDescription))
        if token and len(token.strip()) >= _MIN_TOKEN_LEN
    ]
    return tokens


def renderTaskRecallSection(recall: Dict[str, List[str]]) -> str:
    """把 ``taskDrivenRecall`` 结果渲染成任务书附加段（无内容返回空串）。"""
    labels = {
        "experiences": "相关经验",
        "lessons": "相关教训",
        "skills": "相关技能",
        "preferences": "相关偏好",
    }
    lines: List[str] = []
    for bucket, label in labels.items():
        for item in recall.get(bucket, []):
            text = str(item or "").strip()
            if text:
                lines.append(f"- {label}：{text}")
    if not lines:
        return ""
    return "[任务经验召回]\n" + "\n".join(lines)


def taskDrivenRecall(
    memory_manager,
    taskDescription: str,
    limitPerCategory: int = 5,
) -> Dict[str, List[str]]:
    """任务驱动回忆：按任务描述关键词在经验/教训/技能/偏好四桶内检索。

    检索走 ``MemoryManager.recall(use_semantic=False)`` 的关键词子串通道
    （任务书场景无需向量依赖），每桶取第一个产生命中的关键词，命中内容
    以字符串列表返回；空任务或总开关关闭返回空映射。
    """
    if not _proactiveEnabled():
        return {}
    text = str(taskDescription or "").strip()
    if not text:
        return {}
    tokens = _taskTokens(text)
    if not tokens:
        return {}

    result: Dict[str, List[str]] = {}
    for bucket, category in TASK_CATEGORY_BUCKETS:
        for token in tokens:
            try:
                rows = memory_manager.recall(
                    query=token,
                    category=category,
                    limit=max(1, int(limitPerCategory)),
                    use_semantic=False,
                )
            except Exception as exc:  # noqa: BLE001 — 单桶检索失败不拖垮其余桶
                logger.debug("taskDrivenRecall %s 检索失败: %s", category, exc)
                rows = []
            contents = [
                str(row.get("content", ""))
                for row in (rows or [])
                if isinstance(row, dict) and row.get("content")
            ]
            if contents:
                result[bucket] = contents
                break
    return result
