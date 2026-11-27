"""
时间感知机制 - 轻量时间上下文提示

仅保留每轮可用的季节与临近节日计算；记忆模式分析、事件预测和季节偏好
旧入口已退役。
"""

from __future__ import annotations

import datetime
from neurova.core.logger import get_logger
import threading
import time
from typing import Any, Dict, List

logger = get_logger(__name__)


class TimeAwareness:
    """时间感知模块：提供纯日期计算的时间上下文提示，不读取记忆。"""

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
        """初始化时间感知模块。

        Args:
            memory_manager: 兼容旧调用签名的记忆管理器参数；当前提示不读记忆。
        """
        self._pattern_cache: Dict[str, Any] = {}
        self._prediction_cache: Dict[str, Any] = {}
        self._cache_ttl = 3600
        self._last_cache_time = 0.0
        self._stats = {
            "total_analyses": 0,
            "total_predictions": 0,
            "patterns_detected": 0,
            "predictions_generated": 0,
        }
        self._lock = threading.RLock()

        logger.info("TimeAwareness 初始化完成")

    def get_time_context_hint(self, prediction_days: int = 3) -> str:
        """生成轻量时间上下文提示（纯日期计算，不读记忆，可每轮调用）。

        Returns:
            形如 "季节:冬;临近节日:元旦(2天内)" 的单行提示；无内容返回 ""。
        """
        try:
            season_zh = {"spring": "春", "summer": "夏", "autumn": "秋", "winter": "冬"}
            month = datetime.datetime.now().month
            season = "winter"
            for name, (start, end) in self._SEASONS.items():
                if name == "winter":
                    continue
                if start <= month <= end:
                    season = name
                    break
            if month >= 12 or month <= 2:
                season = "winter"

            parts = [f"季节:{season_zh[season]}"]

            for holiday in self._predict_chinese_holidays(prediction_days)[:2]:
                try:
                    holiday_date = datetime.datetime.fromisoformat(holiday["predicted_date"])
                    days_until = max(0, (holiday_date - datetime.datetime.now()).days + 1)
                    parts.append(f"临近节日:{holiday['name']}({days_until}天内)")
                except (KeyError, ValueError):
                    continue

            return ";".join(parts)
        except Exception as e:
            logger.debug("生成时间上下文提示失败: %s", e)
            return ""

    def _predict_chinese_holidays(self, prediction_days: int) -> List[Dict[str, Any]]:
        """预测预测范围内的公历节日。"""
        try:
            predictions = []
            current_time = datetime.datetime.now()
            end_time = current_time + datetime.timedelta(days=prediction_days)

            for (month, day), name in self._CHINESE_HOLIDAYS.items():
                holiday_date = datetime.datetime(current_time.year, month, day)
                if holiday_date < current_time:
                    holiday_date = datetime.datetime(current_time.year + 1, month, day)

                if holiday_date <= end_time:
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

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息。"""
        with self._lock:
            return {
                **self._stats,
                "cache_age": time.time() - self._last_cache_time if self._last_cache_time else 0,
                "pattern_cache_size": len(self._pattern_cache),
                "prediction_cache_size": len(self._prediction_cache),
            }

    def clear(self) -> None:
        """清空所有数据。"""
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
    """获取时间感知模块单例。"""
    global _time_awareness_instances

    with _time_awareness_lock:
        instance_id = "default"
        if instance_id not in _time_awareness_instances:
            _time_awareness_instances[instance_id] = TimeAwareness(memory_manager=memory_manager)
        return _time_awareness_instances[instance_id]


def reset_time_awareness() -> None:
    """重置时间感知模块单例。"""
    global _time_awareness_instances

    with _time_awareness_lock:
        _time_awareness_instances.clear()


def reset_all_time_awareness() -> None:
    """重置所有时间感知模块单例。"""
    reset_time_awareness()
