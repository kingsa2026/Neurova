"""
情感分析引擎 v1.0.0 - 基于情感中枢引擎的四层情感分类体系
"""

from __future__ import annotations

from neurova.core.logger import get_logger
import threading
from typing import Any, Dict, List, Optional, Tuple

from neurova.cognitive_layers.emotion_context_layer.emotion_hub_engine import (
    AdvancedEmotion,
    BasicEmotion,
    ComplexEmotion,
    SpecialEmotion,
    get_emotion_hub_engine,
)

logger = get_logger(__name__)


class EmotionAnalyzer:
    """
    情感分析引擎

    基于情感中枢引擎的四层情感分类体系，提供：
    - 文本情感分析
    - 情感分数计算
    - 主导情感识别
    - 情感标签生成
    - 情感层次分析
    - 带传导的情感分析
    """

    # 情感层次定义
    _EMOTION_HIERARCHY = {
        "basic": [e.value for e in BasicEmotion],
        "complex": [e.value for e in ComplexEmotion],
        "advanced": [e.value for e in AdvancedEmotion],
        "special": [e.value for e in SpecialEmotion],
    }

    # 情感标签映射
    _EMOTION_TAGS = {
        "joy": ["积极", "快乐", "愉悦"],
        "sadness": ["消极", "悲伤", "低落"],
        "anger": ["消极", "愤怒", "激动"],
        "fear": ["消极", "恐惧", "紧张"],
        "surprise": ["中性", "惊讶", "意外"],
        "disgust": ["消极", "厌恶", "反感"],
        "contempt": ["消极", "蔑视", "不屑"],
        "anticipation": ["积极", "期待", "盼望"],
        "trust": ["积极", "信任", "信赖"],
        "guilt": ["消极", "内疚", "自责"],
        "shame": ["消极", "羞耻", "羞愧"],
        "pride": ["积极", "自豪", "骄傲"],
        "embarrassment": ["消极", "尴尬", "窘迫"],
        "nostalgia": ["中性", "怀旧", "思念"],
        "awe": ["中性", "敬畏", "崇敬"],
        "compassion": ["积极", "同情", "怜悯"],
        "ennui": ["消极", "厌倦", "无聊"],
    }

    def __init__(self, agent_id: str = "default"):
        """初始化情感分析引擎

        Args:
            agent_id: Agent标识符
        """
        self._agent_id = agent_id
        self._hub_engine = get_emotion_hub_engine(agent_id)

        # 统计信息
        self._stats = {
            "total_analyses": 0,
            "dominant_emotions_detected": 0,
            "conduction_analyses": 0,
        }

        # 线程安全
        self._lock = threading.RLock()

        logger.info("EmotionAnalyzer 初始化完成 (agent_id=%s)", agent_id)

    def set_emotion_module(self, module) -> None:
        """注入 memory_layer 的 EmotionModule（补课 7 认知收敛第二批）。

        注入后 analyze() 走 EmotionModule 语义分类器（8 基础情感
        zero-shot，消除 hub 关键词表的"好"字效应）；未注入或失败时
        回退 hub 关键词规则。两引擎分工：EmotionModule=逐记忆持久化
        +主分析源；HubEngine=会话级 17 细粒度状态机（本类消费其状态）。
        """
        self._emotion_module = module

    def analyze(
        self,
        text: str,
        update_state: bool = False,
        blend_factor: float = 0.3,
    ) -> Dict[str, float]:
        """分析文本情感（收敛入口：语义分类器优先，hub 关键词兜底）

        Args:
            text: 输入文本
            update_state: 是否更新情感状态
            blend_factor: 混合因子（仅当update_state=True时使用）

        Returns:
            情感分数字典
        """
        # 收敛路径：EmotionModule 语义分析（主源）——主导情感+强度
        emotion_module = getattr(self, "_emotion_module", None)
        if emotion_module is not None:
            try:
                state = emotion_module.analyze_text_emotion(text)
                if state is not None:
                    intensity = float(getattr(state, "intensity", 0.0) or 0.0)
                    primary = getattr(state, "primary_emotion", None)
                    label = str(getattr(primary, "value", primary) or "neutral")
                    with self._lock:
                        self._stats["total_analyses"] += 1
                        # 中性/零强度 → 空表（与 hub 无命中契约一致，避免注入噪音）
                        scores = {label: intensity} if label != "neutral" and intensity > 0 else {}
                        # 会话状态机照常消费（可选更新）
                        if update_state and scores:
                            self._hub_engine.update_emotional_state(scores, blend_factor)
                        return scores
            except Exception as e:
                logger.warning("EmotionModule 语义分析失败，回退 hub 关键词: %s", e)

        with self._lock:
            try:
                # 使用情感中枢引擎分析
                emotion_scores = self._hub_engine.analyze_text(text)

                # 可选：更新情感状态
                if update_state and emotion_scores:
                    self._hub_engine.update_emotional_state(emotion_scores, blend_factor)

                self._stats["total_analyses"] += 1
                return emotion_scores

            except Exception as e:
                logger.error("情感分析失败: %s", e)
                return {}

    def get_emotion_score(self, emotion: str) -> float:
        """获取指定情感的分数

        Args:
            emotion: 情感名称

        Returns:
            情感分数 (0-1)
        """
        with self._lock:
            distribution = self._hub_engine.get_emotion_distribution()
            return distribution.get(emotion, 0.0)

    def get_dominant_emotion(self) -> Optional[Tuple[str, float]]:
        """获取主导情感及其分数

        Returns:
            (情感名称, 分数) 元组，如果无主导情感则返回None
        """
        with self._lock:
            dominant = self._hub_engine.get_dominant_emotion()
            if dominant is None:
                return None

            score = self._hub_engine.get_emotion_distribution().get(dominant, 0.0)

            self._stats["dominant_emotions_detected"] += 1
            return (dominant, score)

    def get_emotion_tags(self, top_n: int = 3) -> List[str]:
        """获取情感标签

        Args:
            top_n: 返回前N个情感的标签

        Returns:
            情感标签列表
        """
        with self._lock:
            distribution = self._hub_engine.get_emotion_distribution()

            # 按分数排序
            sorted_emotions = sorted(
                distribution.items(),
                key=lambda x: x[1],
                reverse=True,
            )

            tags = []
            for emotion, score in sorted_emotions[:top_n]:
                if score > 0.1:  # 只包含有显著强度的情感
                    emotion_tags = self._EMOTION_TAGS.get(emotion, [])
                    tags.extend(emotion_tags)

            # 去重
            return list(dict.fromkeys(tags))

    def get_emotion_hierarchy(self) -> Dict[str, Dict[str, float]]:
        """获取情感层次分布

        Returns:
            按层次组织的情感分布
        """
        with self._lock:
            distribution = self._hub_engine.get_emotion_distribution()

            hierarchy = {}
            for level, emotions in self._EMOTION_HIERARCHY.items():
                level_scores = {}
                for emotion in emotions:
                    score = distribution.get(emotion, 0.0)
                    if score > 0:
                        level_scores[emotion] = score

                if level_scores:
                    hierarchy[level] = level_scores

            return hierarchy

    def analyze_with_conduction(
        self,
        text: str,
        blend_factor: float = 0.3,
    ) -> Dict[str, Any]:
        """带传导的情感分析

        Args:
            text: 输入文本
            blend_factor: 混合因子

        Returns:
            分析结果字典，包含初始情感、传导后情感、主导情感变化等
        """
        with self._lock:
            try:
                # 初始情感分析
                initial_emotions = self._hub_engine.analyze_text(text)

                # 记录初始主导情感
                initial_dominant = self._hub_engine.get_dominant_emotion()

                # 更新情感状态（会触发传导）
                updated_state = self._hub_engine.update_emotional_state(
                    initial_emotions,
                    blend_factor,
                )

                # 获取传导后主导情感
                final_dominant = self._hub_engine.get_dominant_emotion()

                # 计算情感变化
                emotion_changes = {}
                all_emotions = set(initial_emotions.keys()) | set(updated_state.keys())
                for emotion in all_emotions:
                    initial = initial_emotions.get(emotion, 0.0)
                    final = updated_state.get(emotion, 0.0)
                    change = final - initial
                    if abs(change) > 0.01:  # 只记录有意义的变化
                        emotion_changes[emotion] = {
                            "initial": initial,
                            "final": final,
                            "change": change,
                        }

                self._stats["conduction_analyses"] += 1

                return {
                    "initial_emotions": initial_emotions,
                    "updated_state": updated_state,
                    "initial_dominant": initial_dominant,
                    "final_dominant": final_dominant,
                    "dominant_changed": initial_dominant != final_dominant,
                    "emotion_changes": emotion_changes,
                }

            except Exception as e:
                logger.error("带传导的情感分析失败: %s", e)
                return {
                    "initial_emotions": {},
                    "updated_state": self._hub_engine.get_emotion_distribution(),
                    "initial_dominant": None,
                    "final_dominant": None,
                    "dominant_changed": False,
                    "emotion_changes": {},
                }

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
                "agent_id": self._agent_id,
            }

    def clear(self) -> None:
        """清空所有数据"""
        with self._lock:
            self._hub_engine.clear()
            self._stats = {
                "total_analyses": 0,
                "dominant_emotions_detected": 0,
                "conduction_analyses": 0,
            }
            logger.info("EmotionAnalyzer 数据已清空 (agent_id=%s)", self._agent_id)


# 全局实例管理
_emotion_analyzer_instances: Dict[str, EmotionAnalyzer] = {}
_emotion_analyzer_lock = threading.Lock()


def get_emotion_analyzer(agent_id: str = "default") -> EmotionAnalyzer:
    """获取情感分析引擎单例

    Args:
        agent_id: Agent标识符

    Returns:
        情感分析引擎实例
    """
    global _emotion_analyzer_instances

    with _emotion_analyzer_lock:
        if agent_id not in _emotion_analyzer_instances:
            _emotion_analyzer_instances[agent_id] = EmotionAnalyzer(agent_id=agent_id)
        return _emotion_analyzer_instances[agent_id]


def reset_emotion_analyzer(agent_id: Optional[str] = None) -> None:
    """重置情感分析引擎单例

    Args:
        agent_id: Agent标识符，为None时重置所有
    """
    global _emotion_analyzer_instances

    with _emotion_analyzer_lock:
        if agent_id is None:
            _emotion_analyzer_instances.clear()
        elif agent_id in _emotion_analyzer_instances:
            _emotion_analyzer_instances[agent_id].clear()
            del _emotion_analyzer_instances[agent_id]


def reset_all_emotion_analyzers() -> None:
    """重置所有情感分析引擎单例"""
    reset_emotion_analyzer(None)
