"""
情感传导模块 v1.0.0 - 基于情感中枢引擎

功能:
- 使用情感中枢引擎管理情感状态（四层17种情感）
- 支持情感传导规则
- 根据情感状态调整对话风格
- 情感状态影响记忆温度
- 情感历史记录
- 与用户情感融合（共情）
"""

from __future__ import annotations

import datetime
from neurova.core.logger import get_logger
import threading
from typing import Any, Dict, List, Optional

from neurova.cognitive_layers.emotion_context_layer.emotion_hub_engine import (
    get_emotion_hub_engine,
    reset_emotion_hub_engine,
)

logger = get_logger(__name__)


class EmotionConductionManager:
    """
    情感传导管理器

    封装情感中枢引擎，提供高级情感管理功能：
    - 情感状态管理
    - 文本情感分析
    - 情感传导
    - 温度和风格调节
    - 用户情感融合（共情）
    """

    def __init__(self, agent_id: str = "default"):
        """初始化情感传导管理器

        Args:
            agent_id: Agent标识符
        """
        self._agent_id = agent_id
        self._hub_engine = get_emotion_hub_engine(agent_id)

        # 情感融合配置
        self._fusion_weight = 0.3  # 用户情感融合权重

        # 统计信息
        self._stats = {
            "total_text_analyses": 0,
            "total_state_updates": 0,
            "total_fusions": 0,
            "total_resets": 0,
        }

        # 线程安全
        self._lock = threading.RLock()

        logger.info("EmotionConductionManager 初始化完成 (agent_id=%s)", agent_id)

    def update_emotional_state(
        self,
        emotion_scores: Dict[str, float],
        blend_factor: float = 0.3,
    ) -> Dict[str, float]:
        """更新情感状态

        Args:
            emotion_scores: 情感分数字典
            blend_factor: 混合因子

        Returns:
            更新后的情感状态
        """
        with self._lock:
            try:
                result = self._hub_engine.update_emotional_state(emotion_scores, blend_factor)
                self._stats["total_state_updates"] += 1
                return result
            except Exception as e:
                logger.error("更新情感状态失败: %s", e)
                return self._hub_engine.get_emotion_distribution()

    def get_emotional_state(self) -> Dict[str, float]:
        """获取当前情感状态

        Returns:
            情感状态字典
        """
        with self._lock:
            return self._hub_engine.get_emotion_distribution()

    def get_dominant_emotion(self) -> Optional[str]:
        """获取主导情感

        Returns:
            主导情感名称
        """
        with self._lock:
            return self._hub_engine.get_dominant_emotion()

    def get_emotion_bias(self) -> Dict[str, float]:
        """获取情感偏置

        Returns:
            情感偏置字典
        """
        with self._lock:
            return self._hub_engine.get_emotion_bias()

    def apply_emotion_to_temperature(
        self,
        base_temperature: float,
        emotion_weight: float = 0.2,
    ) -> float:
        """将情感应用到温度

        Args:
            base_temperature: 基础温度
            emotion_weight: 情感权重

        Returns:
            调整后的温度
        """
        with self._lock:
            return self._hub_engine.apply_emotion_to_temperature(base_temperature, emotion_weight)

    def apply_emotion_to_style(self) -> Dict[str, Any]:
        """将情感应用到风格

        Returns:
            风格修饰符字典
        """
        with self._lock:
            return self._hub_engine.get_emotion_style_modifier()

    def get_emotion_history(
        self,
        limit: int = 10,
    ) -> List[Tuple[datetime.datetime, Dict[str, float]]]:
        """获取情感历史

        Args:
            limit: 返回记录数限制

        Returns:
            情感历史列表
        """
        with self._lock:
            history = self._hub_engine._emotion_history
            return history[-limit:] if history else []

    def reset_to_baseline(self) -> None:
        """重置情感状态到基线"""
        with self._lock:
            self._hub_engine._init_emotion_state()
            self._stats["total_resets"] += 1
            logger.info("情感状态已重置到基线 (agent_id=%s)", self._agent_id)

    def merge_with_user_emotion(
        self,
        user_emotion_scores: Dict[str, float],
        fusion_weight: Optional[float] = None,
    ) -> Dict[str, float]:
        """与用户情感融合（共情）

        Args:
            user_emotion_scores: 用户情感分数
            fusion_weight: 融合权重，为None时使用默认值

        Returns:
            融合后的情感状态
        """
        with self._lock:
            try:
                weight = fusion_weight if fusion_weight is not None else self._fusion_weight

                # 获取当前情感状态
                current_state = self._hub_engine.get_emotion_distribution()

                # 融合用户情感
                fused_state = {}
                all_emotions = set(current_state.keys()) | set(user_emotion_scores.keys())

                for emotion in all_emotions:
                    current_score = current_state.get(emotion, 0.0)
                    user_score = user_emotion_scores.get(emotion, 0.0)

                    # 加权融合：当前状态 * (1 - weight) + 用户情感 * weight
                    fused_score = current_score * (1 - weight) + user_score * weight
                    fused_state[emotion] = max(0.0, min(1.0, fused_score))

                # 更新情感状态
                result = self._hub_engine.update_emotional_state(fused_state, blend_factor=1.0)

                self._stats["total_fusions"] += 1
                logger.debug("情感融合完成 (weight=%s)", weight)

                return result

            except Exception as e:
                logger.error("情感融合失败: %s", e)
                return self._hub_engine.get_emotion_distribution()

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息

        Returns:
            统计信息字典
        """
        with self._lock:
            hub_stats = self._hub_engine.get_stats()
            return {
                **self._stats,
                **hub_stats,
                "fusion_weight": self._fusion_weight,
            }

    def analyze_text_emotion(self, text: str) -> Dict[str, float]:
        """分析文本情感

        Args:
            text: 输入文本

        Returns:
            情感分数字典
        """
        with self._lock:
            try:
                result = self._hub_engine.analyze_text(text)
                self._stats["total_text_analyses"] += 1
                return result
            except Exception as e:
                logger.error("文本情感分析失败: %s", e)
                return {}

    def update_from_text(
        self,
        text: str,
        blend_factor: float = 0.3,
    ) -> Dict[str, float]:
        """从文本更新情感状态

        Args:
            text: 输入文本
            blend_factor: 混合因子

        Returns:
            更新后的情感状态
        """
        with self._lock:
            try:
                # 分析文本情感
                emotion_scores = self.analyze_text_emotion(text)

                if not emotion_scores:
                    return self._hub_engine.get_emotion_distribution()

                # 更新情感状态
                result = self.update_emotional_state(emotion_scores, blend_factor)

                logger.debug("从文本更新情感状态: %s", emotion_scores)
                return result

            except Exception as e:
                logger.error("从文本更新情感状态失败: %s", e)
                return self._hub_engine.get_emotion_distribution()


# 全局实例管理
_emotion_conduction_instances: Dict[str, EmotionConductionManager] = {}
_emotion_conduction_lock = threading.Lock()


def get_emotion_conduction_manager(agent_id: str = "default") -> EmotionConductionManager:
    """获取情感传导管理器单例

    Args:
        agent_id: Agent标识符

    Returns:
        情感传导管理器实例
    """
    global _emotion_conduction_instances

    with _emotion_conduction_lock:
        if agent_id not in _emotion_conduction_instances:
            _emotion_conduction_instances[agent_id] = EmotionConductionManager(agent_id=agent_id)
        return _emotion_conduction_instances[agent_id]


def reset_emotion_conduction_manager(agent_id: Optional[str] = None) -> None:
    """重置情感传导管理器单例

    Args:
        agent_id: Agent标识符，为None时重置所有
    """
    global _emotion_conduction_instances

    with _emotion_conduction_lock:
        if agent_id is None:
            _emotion_conduction_instances.clear()
            reset_emotion_hub_engine(None)
        elif agent_id in _emotion_conduction_instances:
            _emotion_conduction_instances[agent_id].reset_to_baseline()
            del _emotion_conduction_instances[agent_id]


def reset_all_emotion_conduction_managers() -> None:
    """重置所有情感传导管理器单例"""
    reset_emotion_conduction_manager(None)
