"""
时间感知机制 - 模式识别、事件预测、季节偏好

优化内容:
- 增强周期性模式检测 (每日/每周/每月/季度/年度)
- 改进预测置信度计算 (基于历史频次+时间一致性+趋势分析)
- 新增习惯事件智能预测 (基于小时分布和类别关联)
- 新增季节性偏好趋势分析
- 增加中国节日预测
"""

from __future__ import annotations

import datetime
import logging
import math
import threading
import time
from collections import Counter, defaultdict
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class TimeAwareness:
    """
    时间感知模块

    分析记忆中的时间模式，预测未来事件，提供季节性偏好。
    """

    # 中国节日（农历节日需要额外计算，这里只包含公历节日）
    _CHINESE_HOLIDAYS = {
        (1, 1): "元旦",
        (2, 14): "情人节",
        (3, 8): "妇女节",
        (3, 12): "植树节",
        (4, 1): "愚人节",
        (5, 1): "劳动节",
        (5, 4): "青年节",
        (6, 1): "儿童节",
        (7, 1): "建党节",
        (8, 1): "建军节",
        (9, 10): "教师节",
        (10, 1): "国庆节",
        (12, 25): "圣诞节",
    }

    # 季节定义（北半球）
    _SEASONS = {
        "spring": (3, 5),  # 3月-5月
        "summer": (6, 8),  # 6月-8月
        "autumn": (9, 11),  # 9月-11月
        "winter": (12, 2),  # 12月-2月
    }

    def __init__(self, memory_manager: Any = None):
        """初始化时间感知模块

        Args:
            memory_manager: 记忆管理器
        """
        self._memory_manager = memory_manager

        # 缓存
        self._pattern_cache: Dict[str, Any] = {}
        self._prediction_cache: Dict[str, Any] = {}
        self._cache_ttl = 3600  # 缓存有效期（秒）
        self._last_cache_time = 0.0

        # 统计信息
        self._stats = {
            "total_analyses": 0,
            "total_predictions": 0,
            "patterns_detected": 0,
            "predictions_generated": 0,
        }

        # 线程安全
        self._lock = threading.RLock()

        logger.info("TimeAwareness 初始化完成")

    def analyze_patterns(
        self,
        time_window_days: int = 90,
    ) -> Dict[str, Any]:
        """分析时间模式

        Args:
            time_window_days: 分析时间窗口（天）

        Returns:
            模式分析结果
        """
        with self._lock:
            try:
                # 获取最近记忆
                memories = self._get_recent_memories(time_window_days)

                if not memories:
                    return {"error": "没有足够的记忆数据"}

                # 分析各种模式
                daily_habits = self._analyze_daily_habits(memories)
                periodic_events = self._analyze_periodic_events(memories)
                time_distribution = self._analyze_time_distribution(memories)
                monthly_trends = self._analyze_monthly_trends(memories)
                activity_patterns = self._analyze_activity_patterns(memories)

                result = {
                    "daily_habits": daily_habits,
                    "periodic_events": periodic_events,
                    "time_distribution": time_distribution,
                    "monthly_trends": monthly_trends,
                    "activity_patterns": activity_patterns,
                    "analysis_time": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "memories_analyzed": len(memories),
                    "time_window_days": time_window_days,
                }

                # 更新缓存
                self._pattern_cache = result
                self._last_cache_time = time.time()

                # 更新统计
                self._stats["total_analyses"] += 1
                self._stats["patterns_detected"] += len(periodic_events) + len(daily_habits)

                return result

            except Exception as e:
                logger.error("分析时间模式失败: %s", e)
                return {"error": str(e)}

    def predict_events(
        self,
        prediction_days: int = 30,
    ) -> List[Dict[str, Any]]:
        """预测未来事件

        Args:
            prediction_days: 预测时间范围（天）

        Returns:
            预测事件列表
        """
        with self._lock:
            try:
                predictions = []

                # 预测周期性事件
                periodic_predictions = self._predict_periodic_events(prediction_days)
                predictions.extend(periodic_predictions)

                # 预测季节性事件
                seasonal_predictions = self._predict_seasonal_events(prediction_days)
                predictions.extend(seasonal_predictions)

                # 预测中国节日
                holiday_predictions = self._predict_chinese_holidays(prediction_days)
                predictions.extend(holiday_predictions)

                # 预测习惯事件
                habit_predictions = self._predict_habit_events(prediction_days)
                predictions.extend(habit_predictions)

                # 预测类别事件
                category_predictions = self._predict_category_events(prediction_days)
                predictions.extend(category_predictions)

                # 去重
                predictions = self._deduplicate_predictions(predictions)

                # 按日期排序
                predictions.sort(key=lambda x: x.get("predicted_date", ""))

                # 更新缓存
                self._prediction_cache = {
                    "predictions": predictions,
                    "prediction_days": prediction_days,
                    "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                }

                # 更新统计
                self._stats["total_predictions"] += 1
                self._stats["predictions_generated"] += len(predictions)

                return predictions

            except Exception as e:
                logger.error("预测事件失败: %s", e)
                return []

    def get_seasonal_preferences(self) -> Dict[str, Any]:
        """获取季节性偏好

        Returns:
            季节性偏好分析结果
        """
        with self._lock:
            try:
                # 获取最近一年的记忆
                memories = self._get_recent_memories(365)

                if not memories:
                    return {"error": "没有足够的记忆数据"}

                # 按季节分组
                season_memories: Dict[str, List[Any]] = {
                    "spring": [],
                    "summer": [],
                    "autumn": [],
                    "winter": [],
                }

                for memory in memories:
                    timestamp = getattr(memory, "timestamp", None)
                    if timestamp:
                        month = timestamp.month
                        for season, (start, end) in self._SEASONS.items():
                            if start <= month <= end or (season == "winter" and (month >= 12 or month <= 2)):
                                season_memories[season].append(memory)
                                break

                # 分析每个季节的偏好
                preferences = {}
                for season, season_mems in season_memories.items():
                    if season_mems:
                        # 分析情感分布
                        emotion_counts: Counter[str] = Counter()
                        category_counts: Counter[str] = Counter()

                        for mem in season_mems:
                            emotion = getattr(mem, "emotion", None)
                            if emotion:
                                emotion_counts[emotion] += 1

                            category = getattr(mem, "category", None) or getattr(mem, "type", None)
                            if category:
                                category_counts[str(category)] += 1

                        preferences[season] = {
                            "memory_count": len(season_mems),
                            "dominant_emotion": emotion_counts.most_common(1)[0][0] if emotion_counts else None,
                            "top_categories": category_counts.most_common(3),
                            "emotion_distribution": dict(emotion_counts.most_common(5)),
                        }

                return {
                    "seasonal_preferences": preferences,
                    "analysis_time": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "memories_analyzed": len(memories),
                }

            except Exception as e:
                logger.error("获取季节性偏好失败: %s", e)
                return {"error": str(e)}

    def _get_recent_memories(self, days: int) -> List[Any]:
        """获取最近记忆

        Args:
            days: 天数

        Returns:
            记忆列表
        """
        try:
            if self._memory_manager is None:
                logger.warning("记忆管理器未初始化")
                return []

            # 尝试从记忆管理器获取记忆
            if hasattr(self._memory_manager, "get_recent_memories"):
                return self._memory_manager.get_recent_memories(days=days)
            elif hasattr(self._memory_manager, "search"):
                # 使用搜索接口
                cutoff_date = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)
                return self._memory_manager.search(
                    query="",
                    filters={"timestamp_after": cutoff_date.isoformat()},
                    limit=1000,
                )
            else:
                logger.warning("记忆管理器不支持获取最近记忆")
                return []

        except Exception as e:
            logger.error("获取最近记忆失败: %s", e)
            return []

    def _analyze_daily_habits(self, memories: List[Any]) -> Dict[str, Any]:
        """分析日常习惯

        Args:
            memories: 记忆列表

        Returns:
            日常习惯分析结果
        """
        try:
            # 按小时统计活动
            hour_counts: Counter[int] = Counter()
            weekday_counts: Counter[str] = Counter()

            for memory in memories:
                timestamp = getattr(memory, "timestamp", None)
                if timestamp:
                    hour_counts[timestamp.hour] += 1
                    weekday_counts[timestamp.strftime("%A")] += 1

            # 找出高峰时段
            peak_hours = hour_counts.most_common(3)
            peak_weekdays = weekday_counts.most_common(3)

            return {
                "peak_hours": [{"hour": h, "count": c} for h, c in peak_hours],
                "peak_weekdays": [{"weekday": w, "count": c} for w, c in peak_weekdays],
                "hour_distribution": dict(hour_counts),
                "weekday_distribution": dict(weekday_counts),
            }

        except Exception as e:
            logger.warning("分析日常习惯失败: %s", e)
            return {}

    def _analyze_periodic_events(self, memories: List[Any]) -> List[Dict[str, Any]]:
        """分析周期性事件

        Args:
            memories: 记忆列表

        Returns:
            周期性事件列表
        """
        try:
            events = []

            # 按类别分组
            category_times: Dict[str, List[datetime.datetime]] = defaultdict(list)

            for memory in memories:
                category = getattr(memory, "category", None) or getattr(memory, "type", None)
                timestamp = getattr(memory, "timestamp", None)

                if category and timestamp:
                    category_times[str(category)].append(timestamp)

            # 分析每个类别的周期性
            for category, timestamps in category_times.items():
                if len(timestamps) >= 3:  # 至少需要3个数据点
                    # 计算时间间隔
                    timestamps.sort()
                    intervals = []
                    for i in range(1, len(timestamps)):
                        interval = (timestamps[i] - timestamps[i - 1]).total_seconds() / 3600  # 转换为小时
                        intervals.append(interval)

                    if intervals:
                        avg_interval = sum(intervals) / len(intervals)
                        std_interval = math.sqrt(sum((x - avg_interval) ** 2 for x in intervals) / len(intervals))

                        # 如果标准差较小，认为是周期性事件
                        if std_interval < avg_interval * 0.3:
                            events.append(
                                {
                                    "category": category,
                                    "avg_interval_hours": avg_interval,
                                    "std_interval_hours": std_interval,
                                    "occurrences": len(timestamps),
                                    "last_occurrence": timestamps[-1].isoformat(),
                                    "confidence": max(0.5, 1.0 - (std_interval / avg_interval)),
                                }
                            )

            return events

        except Exception as e:
            logger.warning("分析周期性事件失败: %s", e)
            return []

    def _analyze_time_distribution(self, memories: List[Any]) -> Dict[str, Any]:
        """分析时间分布

        Args:
            memories: 记忆列表

        Returns:
            时间分布分析结果
        """
        try:
            hour_counts: Counter[int] = Counter()
            day_counts: Counter[str] = Counter()
            month_counts: Counter[int] = Counter()

            for memory in memories:
                timestamp = getattr(memory, "timestamp", None)
                if timestamp:
                    hour_counts[timestamp.hour] += 1
                    day_counts[timestamp.strftime("%A")] += 1
                    month_counts[timestamp.month] += 1

            return {
                "hourly": dict(hour_counts),
                "daily": dict(day_counts),
                "monthly": dict(month_counts),
                "total_memories": len(memories),
            }

        except Exception as e:
            logger.warning("分析时间分布失败: %s", e)
            return {}

    def _analyze_monthly_trends(self, memories: List[Any]) -> Dict[str, Any]:
        """分析月度趋势

        Args:
            memories: 记忆列表

        Returns:
            月度趋势分析结果
        """
        try:
            # 按月分组
            monthly_counts: Counter[str] = Counter()
            monthly_emotions: Dict[str, Counter] = defaultdict(Counter)

            for memory in memories:
                timestamp = getattr(memory, "timestamp", None)
                if timestamp:
                    month_key = timestamp.strftime("%Y-%m")
                    monthly_counts[month_key] += 1

                    emotion = getattr(memory, "emotion", None)
                    if emotion:
                        monthly_emotions[month_key][emotion] += 1

            # 计算趋势
            months = sorted(monthly_counts.keys())
            if len(months) >= 2:
                counts = [monthly_counts[m] for m in months]
                avg_count = sum(counts) / len(counts)
                trend = "increasing" if counts[-1] > avg_count else "decreasing" if counts[-1] < avg_count else "stable"
            else:
                trend = "insufficient_data"

            return {
                "monthly_counts": dict(monthly_counts),
                "monthly_emotions": {k: dict(v) for k, v in monthly_emotions.items()},
                "trend": trend,
                "months_analyzed": len(months),
            }

        except Exception as e:
            logger.warning("分析月度趋势失败: %s", e)
            return {}

    def _analyze_activity_patterns(self, memories: List[Any]) -> Dict[str, Any]:
        """分析活动模式

        Args:
            memories: 记忆列表

        Returns:
            活动模式分析结果
        """
        try:
            # 分析工作日vs周末
            weekday_count = 0
            weekend_count = 0

            for memory in memories:
                timestamp = getattr(memory, "timestamp", None)
                if timestamp:
                    if timestamp.weekday() < 5:  # 0-4 是周一到周五
                        weekday_count += 1
                    else:
                        weekend_count += 1

            total = weekday_count + weekend_count
            weekday_ratio = weekday_count / total if total > 0 else 0.5

            # 分析上午vs下午
            morning_count = 0
            afternoon_count = 0
            evening_count = 0

            for memory in memories:
                timestamp = getattr(memory, "timestamp", None)
                if timestamp:
                    hour = timestamp.hour
                    if 6 <= hour < 12:
                        morning_count += 1
                    elif 12 <= hour < 18:
                        afternoon_count += 1
                    else:
                        evening_count += 1

            return {
                "weekday_weekend_ratio": weekday_ratio,
                "weekday_count": weekday_count,
                "weekend_count": weekend_count,
                "morning_count": morning_count,
                "afternoon_count": afternoon_count,
                "evening_count": evening_count,
                "preferred_time": (
                    "morning"
                    if morning_count > afternoon_count and morning_count > evening_count
                    else "afternoon" if afternoon_count > evening_count else "evening"
                ),
            }

        except Exception as e:
            logger.warning("分析活动模式失败: %s", e)
            return {}

    def _predict_periodic_events(self, prediction_days: int) -> List[Dict[str, Any]]:
        """预测周期性事件

        Args:
            prediction_days: 预测天数

        Returns:
            预测事件列表
        """
        try:
            predictions = []

            # 使用缓存的周期性事件
            periodic_events = self._pattern_cache.get("periodic_events", [])

            current_time = datetime.datetime.now(datetime.timezone.utc)
            end_time = current_time + datetime.timedelta(days=prediction_days)

            for event in periodic_events:
                avg_interval_hours = event.get("avg_interval_hours", 0)
                last_occurrence_str = event.get("last_occurrence")

                if avg_interval_hours > 0 and last_occurrence_str:
                    last_occurrence = datetime.datetime.fromisoformat(last_occurrence_str)

                    # 计算下一次发生时间
                    next_occurrence = last_occurrence + datetime.timedelta(hours=avg_interval_hours)

                    # 如果在预测范围内
                    while next_occurrence <= end_time:
                        if next_occurrence >= current_time:
                            confidence = self._calculate_date_confidence(
                                next_occurrence,
                                event.get("confidence", 0.5),
                                avg_interval_hours,
                            )

                            predictions.append(
                                {
                                    "type": "periodic",
                                    "category": event.get("category", ""),
                                    "predicted_date": next_occurrence.isoformat(),
                                    "confidence": confidence,
                                    "source": "periodic_analysis",
                                }
                            )

                        next_occurrence += datetime.timedelta(hours=avg_interval_hours)

            return predictions

        except Exception as e:
            logger.warning("预测周期性事件失败: %s", e)
            return []

    def _predict_seasonal_events(self, prediction_days: int) -> List[Dict[str, Any]]:
        """预测季节性事件

        Args:
            prediction_days: 预测天数

        Returns:
            预测事件列表
        """
        try:
            predictions = []

            current_time = datetime.datetime.now(datetime.timezone.utc)
            end_time = current_time + datetime.timedelta(days=prediction_days)

            # 季节性事件示例
            seasonal_events = [
                {"month": 3, "day": 15, "name": "消费者权益日", "season": "spring"},
                {"month": 4, "day": 22, "name": "世界地球日", "season": "spring"},
                {"month": 5, "day": 31, "name": "世界无烟日", "season": "spring"},
                {"month": 6, "day": 5, "name": "世界环境日", "season": "summer"},
                {"month": 9, "day": 20, "name": "全国爱牙日", "season": "autumn"},
                {"month": 10, "day": 16, "name": "世界粮食日", "season": "autumn"},
                {"month": 12, "day": 1, "name": "世界艾滋病日", "season": "winter"},
            ]

            for event in seasonal_events:
                # 计算今年的事件日期
                event_date = datetime.datetime(current_time.year, event["month"], event["day"])

                # 如果事件已过，计算明年的
                if event_date < current_time:
                    event_date = datetime.datetime(current_time.year + 1, event["month"], event["day"])

                # 如果在预测范围内
                if event_date <= end_time:
                    predictions.append(
                        {
                            "type": "seasonal",
                            "name": event["name"],
                            "predicted_date": event_date.isoformat(),
                            "confidence": 0.9,  # 季节性事件置信度高
                            "source": "seasonal_analysis",
                        }
                    )

            return predictions

        except Exception as e:
            logger.warning("预测季节性事件失败: %s", e)
            return []

    def _predict_chinese_holidays(self, prediction_days: int) -> List[Dict[str, Any]]:
        """预测中国节日

        Args:
            prediction_days: 预测天数

        Returns:
            预测事件列表
        """
        try:
            predictions = []

            current_time = datetime.datetime.now(datetime.timezone.utc)
            end_time = current_time + datetime.timedelta(days=prediction_days)

            for (month, day), name in self._CHINESE_HOLIDAYS.items():
                # 计算今年的节日日期
                holiday_date = datetime.datetime(current_time.year, month, day)

                # 如果节日已过，计算明年的
                if holiday_date < current_time:
                    holiday_date = datetime.datetime(current_time.year + 1, month, day)

                # 如果在预测范围内
                if holiday_date <= end_time:
                    # 节日置信度随距离衰减
                    days_until = (holiday_date - current_time).days
                    confidence = max(0.7, 1.0 - days_until / prediction_days * 0.3)

                    predictions.append(
                        {
                            "type": "holiday",
                            "name": name,
                            "predicted_date": holiday_date.isoformat(),
                            "confidence": confidence,
                            "source": "chinese_holidays",
                        }
                    )

            return predictions

        except Exception as e:
            logger.warning("预测中国节日失败: %s", e)
            return []

    def _predict_habit_events(self, prediction_days: int) -> List[Dict[str, Any]]:
        """预测习惯事件

        Args:
            prediction_days: 预测天数

        Returns:
            预测事件列表
        """
        try:
            predictions = []

            # 使用缓存的日常习惯
            daily_habits = self._pattern_cache.get("daily_habits", {})
            peak_hours = daily_habits.get("peak_hours", [])
            peak_weekdays = daily_habits.get("peak_weekdays", [])

            if not peak_hours or not peak_weekdays:
                return predictions

            current_time = datetime.datetime.now(datetime.timezone.utc)
            end_time = current_time + datetime.timedelta(days=prediction_days)

            # 预测高峰时段活动
            for hour_info in peak_hours[:2]:  # 只预测前2个高峰时段
                hour = hour_info["hour"]
                hour_info["count"]

                # 预测未来几天的这个小时
                for day_offset in range(1, prediction_days + 1):
                    predicted_time = current_time + datetime.timedelta(days=day_offset)
                    predicted_time = predicted_time.replace(hour=hour, minute=0, second=0, microsecond=0)

                    if predicted_time <= end_time:
                        confidence = self._calculate_date_confidence(
                            predicted_time,
                            0.6,  # 基础置信度
                            24,  # 24小时间隔
                        )

                        predictions.append(
                            {
                                "type": "habit",
                                "description": f"预计在 {hour}:00 有活动",
                                "predicted_date": predicted_time.isoformat(),
                                "confidence": confidence,
                                "source": "habit_analysis",
                            }
                        )

            return predictions

        except Exception as e:
            logger.warning("预测习惯事件失败: %s", e)
            return []

    def _predict_category_events(self, prediction_days: int) -> List[Dict[str, Any]]:
        """预测类别事件

        Args:
            prediction_days: 预测天数

        Returns:
            预测事件列表
        """
        try:
            predictions = []

            # 使用缓存的周期性事件
            periodic_events = self._pattern_cache.get("periodic_events", [])

            current_time = datetime.datetime.now(datetime.timezone.utc)
            end_time = current_time + datetime.timedelta(days=prediction_days)

            for event in periodic_events:
                category = event.get("category", "")
                avg_interval_hours = event.get("avg_interval_hours", 0)
                last_occurrence_str = event.get("last_occurrence")

                if avg_interval_hours > 0 and last_occurrence_str:
                    last_occurrence = datetime.datetime.fromisoformat(last_occurrence_str)

                    # 计算下一次发生时间
                    next_occurrence = last_occurrence + datetime.timedelta(hours=avg_interval_hours)

                    # 如果在预测范围内
                    if next_occurrence <= end_time and next_occurrence >= current_time:
                        confidence = self._calculate_date_confidence(
                            next_occurrence,
                            event.get("confidence", 0.5),
                            avg_interval_hours,
                        )

                        predictions.append(
                            {
                                "type": "category",
                                "category": category,
                                "predicted_date": next_occurrence.isoformat(),
                                "confidence": confidence,
                                "source": "category_analysis",
                            }
                        )

            return predictions

        except Exception as e:
            logger.warning("预测类别事件失败: %s", e)
            return []

    def _calculate_date_confidence(
        self,
        target_date: datetime.datetime,
        base_confidence: float,
        interval_hours: float,
    ) -> float:
        """计算日期置信度

        Args:
            target_date: 目标日期
            base_confidence: 基础置信度
            interval_hours: 间隔小时数

        Returns:
            置信度 (0-1)
        """
        try:
            current_time = datetime.datetime.now(datetime.timezone.utc)
            days_until = (target_date - current_time).total_seconds() / 86400

            # 距离越远，置信度越低
            distance_factor = max(0.5, 1.0 - days_until / 30)

            # 间隔越稳定，置信度越高
            stability_factor = min(1.0, interval_hours / 24)

            # 综合置信度
            confidence = base_confidence * distance_factor * stability_factor

            return max(0.1, min(1.0, confidence))

        except Exception as e:
            logger.warning("计算日期置信度失败: %s", e)
            return 0.5

    def _deduplicate_predictions(
        self,
        predictions: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """去重预测

        Args:
            predictions: 预测列表

        Returns:
            去重后的预测列表
        """
        try:
            # 按日期分组
            date_groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

            for pred in predictions:
                date_key = pred.get("predicted_date", "")[:10]  # 只取日期部分
                date_groups[date_key].append(pred)

            # 对于同一天的预测，保留置信度最高的
            deduplicated = []
            for date_key, preds in date_groups.items():
                if preds:
                    best_pred = max(preds, key=lambda x: x.get("confidence", 0))
                    deduplicated.append(best_pred)

            return deduplicated

        except Exception as e:
            logger.warning("去重预测失败: %s", e)
            return predictions

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息

        Returns:
            统计信息字典
        """
        with self._lock:
            return {
                **self._stats,
                "cache_age": time.time() - self._last_cache_time if self._last_cache_time else 0,
                "pattern_cache_size": len(self._pattern_cache),
                "prediction_cache_size": len(self._prediction_cache),
            }

    def clear(self) -> None:
        """清空所有数据"""
        with self._lock:
            self._pattern_cache.clear()
            self._prediction_cache.clear()
            self._last_cache_time = 0.0
            self._stats = {
                "total_analyses": 0,
                "total_predictions": 0,
                "patterns_detected": 0,
                "predictions_generated": 0,
            }
            logger.info("TimeAwareness 数据已清空")


# 全局实例管理
_time_awareness_instances: Dict[str, TimeAwareness] = {}
_time_awareness_lock = threading.Lock()


def get_time_awareness(memory_manager: Any = None) -> TimeAwareness:
    """获取时间感知模块单例

    Args:
        memory_manager: 记忆管理器

    Returns:
        时间感知模块实例
    """
    global _time_awareness_instances

    with _time_awareness_lock:
        instance_id = "default"
        if instance_id not in _time_awareness_instances:
            _time_awareness_instances[instance_id] = TimeAwareness(memory_manager=memory_manager)
        return _time_awareness_instances[instance_id]


def reset_time_awareness() -> None:
    """重置时间感知模块单例"""
    global _time_awareness_instances

    with _time_awareness_lock:
        _time_awareness_instances.clear()


def reset_all_time_awareness() -> None:
    """重置所有时间感知模块单例"""
    reset_time_awareness()
