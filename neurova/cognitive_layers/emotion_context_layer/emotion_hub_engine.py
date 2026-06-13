"""
情感中枢引擎 (Emotion Hub Engine) v1.0.0
=============================================

基于四层情感分类体系：
1. 基本情感（原始情感）- 5种
2. 复合情感（派生情感）- 4种
3. 高级情感（社会性与道德性情感）- 4种
4. 特殊情感 - 4种

总计：17种情感类型，形成完整的情感生态系统。
"""

from __future__ import annotations

import datetime
import logging
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class BasicEmotion(str, Enum):
    """基本情感（原始情感）- 5种"""

    JOY = "joy"  # 喜悦
    SADNESS = "sadness"  # 悲伤
    ANGER = "anger"  # 愤怒
    FEAR = "fear"  # 恐惧
    SURPRISE = "surprise"  # 惊讶


class ComplexEmotion(str, Enum):
    """复合情感（派生情感）- 4种"""

    DISGUST = "disgust"  # 厌恶
    CONTEMPT = "contempt"  # 蔑视
    ANTICIPATION = "anticipation"  # 期待
    TRUST = "trust"  # 信任


class AdvancedEmotion(str, Enum):
    """高级情感（社会性与道德性情感）- 4种"""

    GUILT = "guilt"  # 内疚
    SHAME = "shame"  # 羞耻
    PRIDE = "pride"  # 自豪
    EMBARRASSMENT = "embarrassment"  # 尴尬


class SpecialEmotion(str, Enum):
    """特殊情感 - 4种"""

    NOSTALGIA = "nostalgia"  # 怀旧
    AWE = "awe"  # 敬畏
    COMPASSION = "compassion"  # 同情
    ENNUI = "ennui"  # 厌倦


# 所有情感类型的并集
AllEmotion = BasicEmotion | ComplexEmotion | AdvancedEmotion | SpecialEmotion


@dataclass
class EmotionConductionRule:
    """情感传导规则"""

    source_emotion: str
    target_emotion: str
    probability: float  # 传导概率 (0-1)
    intensity_factor: float = 1.0  # 强度因子
    conditions: Dict[str, Any] = field(default_factory=dict)  # 传导条件
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_emotion": self.source_emotion,
            "target_emotion": self.target_emotion,
            "probability": self.probability,
            "intensity_factor": self.intensity_factor,
            "conditions": self.conditions,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EmotionConductionRule":
        return cls(
            source_emotion=data["source_emotion"],
            target_emotion=data["target_emotion"],
            probability=data["probability"],
            intensity_factor=data.get("intensity_factor", 1.0),
            conditions=data.get("conditions", {}),
            description=data.get("description", ""),
        )


class EmotionHubEngine:
    """
    情感中枢引擎

    管理四层17种情感状态，支持情感分析、传导、温度调节等功能。
    线程安全，每个Agent拥有独立实例。
    """

    # 情感关键词映射表
    _EMOTION_KEYWORDS: Dict[str, List[str]] = {
        "joy": [
            "开心",
            "快乐",
            "高兴",
            "喜悦",
            "幸福",
            "愉快",
            "兴奋",
            "欣喜",
            "欢乐",
            "满足",
            "happy",
            "joy",
            "glad",
            "excited",
            "pleased",
        ],
        "sadness": [
            "悲伤",
            "难过",
            "伤心",
            "忧郁",
            "沮丧",
            "失落",
            "痛苦",
            "哀伤",
            "sad",
            "sorrow",
            "grief",
            "depressed",
            "melancholy",
        ],
        "anger": [
            "愤怒",
            "生气",
            "恼火",
            "暴怒",
            "气愤",
            "恼怒",
            "愤慨",
            "angry",
            "furious",
            "rage",
            "irritated",
            "annoyed",
        ],
        "fear": [
            "恐惧",
            "害怕",
            "担心",
            "焦虑",
            "紧张",
            "不安",
            "惊恐",
            "畏惧",
            "afraid",
            "fear",
            "anxious",
            "worried",
            "scared",
        ],
        "surprise": ["惊讶", "吃惊", "意外", "震惊", "惊奇", "诧异", "surprised", "astonished", "amazed", "shocked"],
        "disgust": ["厌恶", "恶心", "反感", "讨厌", "嫌弃", "disgusted", "repulsed", "revolted", "nauseated"],
        "contempt": ["蔑视", "鄙视", "轻蔑", "看不起", "不屑", "contempt", "disdain", "scorn", "despise"],
        "anticipation": ["期待", "盼望", "期望", "憧憬", "向往", "anticipation", "expectation", "looking forward"],
        "trust": ["信任", "信赖", "相信", "依赖", "trust", "rely", "believe", "confidence"],
        "guilt": ["内疚", "愧疚", "自责", "悔恨", "guilt", "remorse", "regret", "contrite"],
        "shame": ["羞耻", "羞愧", "丢脸", "惭愧", "shame", "embarrassed", "humiliated", "ashamed"],
        "pride": ["自豪", "骄傲", "得意", "光荣", "proud", "pride", "triumphant", "victorious"],
        "embarrassment": ["尴尬", "窘迫", "难为情", "不好意思", "embarrassed", "awkward", "self-conscious"],
        "nostalgia": ["怀旧", "思念", "怀念", "nostalgia", "reminisce", "miss", "longing"],
        "awe": ["敬畏", "崇敬", "惊叹", "awe", "reverence", "wonder", "admiration"],
        "compassion": ["同情", "怜悯", "慈悲", "心疼", "compassion", "sympathy", "empathy", "pity"],
        "ennui": ["厌倦", "无聊", "烦闷", "倦怠", "ennui", "boredom", "tedium", "weariness"],
    }

    # 情感强度修饰词
    _INTENSITY_MODIFIERS: Dict[str, float] = {
        "非常": 1.5,
        "极其": 2.0,
        "特别": 1.4,
        "十分": 1.3,
        "相当": 1.2,
        "有点": 0.7,
        "稍微": 0.6,
        "略微": 0.5,
        "一点": 0.6,
        "些许": 0.5,
        "very": 1.5,
        "extremely": 2.0,
        "quite": 1.2,
        "somewhat": 0.7,
        "slightly": 0.6,
    }

    def __init__(self, agent_id: str = "default"):
        """初始化情感中枢引擎

        Args:
            agent_id: Agent标识符
        """
        self._agent_id = agent_id

        # 线程锁（必须在 _init_emotion_state 之前初始化）
        self._lock = threading.RLock()

        # 情感状态：17种情感的强度值 (0-1)
        self._emotion_state: Dict[str, float] = {}
        self._init_emotion_state()

        # 情感基线：长期情感倾向
        self._emotion_baseline: Dict[str, float] = {}
        self._init_emotion_baseline()

        # 情感历史记录
        self._emotion_history: List[Tuple[datetime.datetime, Dict[str, float]]] = []
        self._max_history = 100

        # 情感传导规则
        self._conduction_rules: List[EmotionConductionRule] = []
        self._init_default_rules()

        # 统计信息
        self._stats = {
            "total_analyses": 0,
            "total_updates": 0,
            "dominant_emotion_changes": 0,
            "conduction_events": 0,
        }

        logger.info("EmotionHubEngine 初始化完成 (agent_id=%s)", agent_id)

    def _init_emotion_state(self) -> None:
        """初始化情感状态为中性"""
        with self._lock:
            # 基本情感初始化为0
            for emotion in BasicEmotion:
                self._emotion_state[emotion.value] = 0.0
            # 复合情感初始化为0
            for emotion in ComplexEmotion:
                self._emotion_state[emotion.value] = 0.0
            # 高级情感初始化为0
            for emotion in AdvancedEmotion:
                self._emotion_state[emotion.value] = 0.0
            # 特殊情感初始化为0
            for emotion in SpecialEmotion:
                self._emotion_state[emotion.value] = 0.0

    def _init_emotion_baseline(self) -> None:
        """初始化情感基线（默认中性偏积极）"""
        with self._lock:
            # 默认基线：轻微的积极倾向
            self._emotion_baseline = {
                BasicEmotion.JOY.value: 0.1,
                BasicEmotion.SADNESS.value: 0.0,
                BasicEmotion.ANGER.value: 0.0,
                BasicEmotion.FEAR.value: 0.0,
                BasicEmotion.SURPRISE.value: 0.05,
                ComplexEmotion.TRUST.value: 0.1,
                ComplexEmotion.ANTICIPATION.value: 0.1,
            }

    def _init_default_rules(self) -> None:
        """初始化默认情感传导规则"""
        with self._lock:
            self._conduction_rules = [
                # 基本情感传导
                EmotionConductionRule("joy", "trust", 0.3, 0.8, description="喜悦增强信任"),
                EmotionConductionRule("joy", "anticipation", 0.2, 0.7, description="喜悦产生期待"),
                EmotionConductionRule("sadness", "fear", 0.2, 0.6, description="悲伤可能引发恐惧"),
                EmotionConductionRule("anger", "disgust", 0.3, 0.7, description="愤怒可能转为厌恶"),
                EmotionConductionRule("fear", "surprise", 0.2, 0.5, description="恐惧可能引发惊讶"),
                # 复合情感传导
                EmotionConductionRule("trust", "joy", 0.2, 0.6, description="信任带来喜悦"),
                EmotionConductionRule("anticipation", "joy", 0.3, 0.7, description="期待实现带来喜悦"),
                EmotionConductionRule("disgust", "anger", 0.2, 0.6, description="厌恶可能转为愤怒"),
                EmotionConductionRule("contempt", "anger", 0.2, 0.5, description="蔑视可能引发愤怒"),
                # 高级情感传导
                EmotionConductionRule("guilt", "sadness", 0.3, 0.8, description="内疚引发悲伤"),
                EmotionConductionRule("shame", "sadness", 0.3, 0.7, description="羞耻引发悲伤"),
                EmotionConductionRule("pride", "joy", 0.4, 0.9, description="自豪带来喜悦"),
                EmotionConductionRule("embarrassment", "shame", 0.2, 0.6, description="尴尬可能转为羞耻"),
                # 特殊情感传导
                EmotionConductionRule("nostalgia", "sadness", 0.2, 0.5, description="怀旧可能引发淡淡悲伤"),
                EmotionConductionRule("nostalgia", "joy", 0.3, 0.6, description="怀旧也可能带来温暖喜悦"),
                EmotionConductionRule("awe", "fear", 0.1, 0.4, description="敬畏可能包含一丝恐惧"),
                EmotionConductionRule("compassion", "sadness", 0.2, 0.5, description="同情可能引发悲伤"),
                EmotionConductionRule("ennui", "sadness", 0.2, 0.4, description="厌倦可能引发悲伤"),
            ]

    def analyze_text(self, text: str) -> Dict[str, float]:
        """分析文本中的情感

        Args:
            text: 输入文本

        Returns:
            情感强度字典 {emotion: intensity}
        """
        with self._lock:
            try:
                if not text:
                    return {}

                text_lower = text.lower()
                emotion_scores: Dict[str, float] = {}

                # 检测每种情感的关键词
                for emotion, keywords in self._EMOTION_KEYWORDS.items():
                    score = 0.0
                    for keyword in keywords:
                        if keyword in text_lower:
                            # 基础分数
                            base_score = 1.0

                            # 检查强度修饰词
                            for modifier, multiplier in self._INTENSITY_MODIFIERS.items():
                                if modifier in text_lower:
                                    base_score *= multiplier
                                    break

                            score += base_score

                    if score > 0:
                        # 归一化到 0-1 范围
                        emotion_scores[emotion] = min(1.0, score / 3.0)

                # 更新统计
                self._stats["total_analyses"] += 1

                logger.debug("文本情感分析结果: %s", emotion_scores)
                return emotion_scores

            except Exception as e:
                logger.error("文本情感分析失败: %s", e)
                return {}

    def update_emotional_state(
        self,
        emotion_scores: Dict[str, float],
        blend_factor: float = 0.3,
    ) -> Dict[str, float]:
        """更新情感状态（混合新情感与当前状态）

        Args:
            emotion_scores: 新情感分数
            blend_factor: 混合因子 (0=完全保留旧状态, 1=完全使用新状态)

        Returns:
            更新后的情感状态
        """
        with self._lock:
            try:
                if not emotion_scores:
                    return self._emotion_state.copy()

                old_dominant = self.get_dominant_emotion()

                # 混合新旧情感
                for emotion, new_score in emotion_scores.items():
                    if emotion in self._emotion_state:
                        old_score = self._emotion_state[emotion]
                        # 加权混合
                        blended = old_score * (1 - blend_factor) + new_score * blend_factor
                        # 应用基线影响
                        baseline = self._emotion_baseline.get(emotion, 0.0)
                        final = blended * 0.9 + baseline * 0.1
                        # 限制在 0-1 范围
                        self._emotion_state[emotion] = max(0.0, min(1.0, final))

                # 自然衰减：未被激活的情感逐渐衰减
                self._apply_decay()

                # 应用情感传导
                self._apply_conduction()

                # 记录历史
                self._record_history()

                # 检测主导情感变化
                new_dominant = self.get_dominant_emotion()
                if old_dominant != new_dominant:
                    self._stats["dominant_emotion_changes"] += 1

                # 更新统计
                self._stats["total_updates"] += 1

                return self._emotion_state.copy()

            except Exception as e:
                logger.error("更新情感状态失败: %s", e)
                return self._emotion_state.copy()

    def _apply_decay(self, decay_rate: float = 0.05) -> None:
        """应用情感自然衰减

        Args:
            decay_rate: 衰减率
        """
        for emotion in self._emotion_state:
            current = self._emotion_state[emotion]
            baseline = self._emotion_baseline.get(emotion, 0.0)
            # 向基线衰减
            diff = current - baseline
            self._emotion_state[emotion] = current - diff * decay_rate

    def _apply_conduction(self) -> None:
        """应用情感传导规则"""
        import random

        for rule in self._conduction_rules:
            source_score = self._emotion_state.get(rule.source_emotion, 0.0)

            # 源情感强度足够高时才可能传导
            if source_score > 0.3:
                # 计算传导概率
                conduction_prob = rule.probability * source_score

                if random.random() < conduction_prob:
                    # 应用传导
                    target_score = self._emotion_state.get(rule.target_emotion, 0.0)
                    conduction_amount = source_score * rule.intensity_factor * 0.2

                    new_target = min(1.0, target_score + conduction_amount)
                    self._emotion_state[rule.target_emotion] = new_target

                    self._stats["conduction_events"] += 1
                    logger.debug("情感传导: %.2f -> %s (+%s)", rule.source_emotion, rule.target_emotion, conduction_amount)

    def _record_history(self) -> None:
        """记录情感历史"""
        self._emotion_history.append(
            (
                datetime.datetime.now(datetime.timezone.utc),
                self._emotion_state.copy(),
            )
        )

        # 限制历史长度
        if len(self._emotion_history) > self._max_history:
            self._emotion_history = self._emotion_history[-self._max_history :]

    def get_dominant_emotion(self) -> Optional[str]:
        """获取当前主导情感

        Returns:
            主导情感名称，如果所有情感强度都很低则返回None
        """
        with self._lock:
            if not self._emotion_state:
                return None

            max_emotion = max(self._emotion_state.items(), key=lambda x: x[1])

            # 只有强度超过阈值才认为有主导情感
            if max_emotion[1] > 0.1:
                return max_emotion[0]
            return None

    def get_emotion_bias(self) -> Dict[str, float]:
        """获取情感偏置（用于温度调节等）

        Returns:
            情感偏置字典，正值表示积极，负值表示消极
        """
        with self._lock:
            bias = {}

            # 积极情感
            positive_emotions = {"joy", "trust", "anticipation", "pride", "awe", "compassion"}
            # 消极情感
            negative_emotions = {"sadness", "anger", "fear", "disgust", "contempt", "guilt", "shame", "ennui"}

            for emotion, score in self._emotion_state.items():
                if emotion in positive_emotions:
                    bias[emotion] = score * 0.5  # 正向偏置
                elif emotion in negative_emotions:
                    bias[emotion] = -score * 0.5  # 负向偏置
                else:
                    bias[emotion] = 0.0

            return bias

    def apply_emotion_to_temperature(
        self,
        base_temperature: float,
        emotion_weight: float = 0.2,
    ) -> float:
        """将情感状态应用到温度参数

        Args:
            base_temperature: 基础温度
            emotion_weight: 情感影响权重

        Returns:
            调整后的温度
        """
        with self._lock:
            try:
                bias = self.get_emotion_bias()
                total_bias = sum(bias.values())

                # 积极情感增加温度（更创造性），消极情感降低温度（更保守）
                adjusted = base_temperature + total_bias * emotion_weight

                # 限制在合理范围
                return max(0.1, min(2.0, adjusted))

            except Exception as e:
                logger.error("情感温度调节失败: %s", e)
                return base_temperature

    def get_emotion_style_modifier(self) -> Dict[str, Any]:
        """获取情感风格修饰符（用于调整回复风格）

        Returns:
            风格修饰符字典
        """
        with self._lock:
            dominant = self.get_dominant_emotion()

            # 默认风格
            style = {
                "tone": "neutral",
                "warmth": 0.5,
                "formality": 0.5,
                "verbosity": 0.5,
                "empathy": 0.5,
            }

            if dominant is None:
                return style

            # 根据主导情感调整风格
            emotion_styles = {
                "joy": {"tone": "cheerful", "warmth": 0.8, "verbosity": 0.7},
                "sadness": {"tone": "gentle", "warmth": 0.7, "empathy": 0.8},
                "anger": {"tone": "firm", "warmth": 0.3, "formality": 0.7},
                "fear": {"tone": "reassuring", "warmth": 0.6, "empathy": 0.7},
                "surprise": {"tone": "curious", "warmth": 0.6, "verbosity": 0.6},
                "disgust": {"tone": "distanced", "warmth": 0.3, "formality": 0.6},
                "contempt": {"tone": "dismissive", "warmth": 0.2, "formality": 0.7},
                "anticipation": {"tone": "enthusiastic", "warmth": 0.7, "verbosity": 0.6},
                "trust": {"tone": "warm", "warmth": 0.8, "empathy": 0.7},
                "guilt": {"tone": "apologetic", "warmth": 0.6, "empathy": 0.8},
                "shame": {"tone": "humble", "warmth": 0.5, "formality": 0.6},
                "pride": {"tone": "confident", "warmth": 0.6, "verbosity": 0.6},
                "embarrassment": {"tone": "sheepish", "warmth": 0.6, "empathy": 0.6},
                "nostalgia": {"tone": "reflective", "warmth": 0.7, "verbosity": 0.6},
                "awe": {"tone": "reverent", "warmth": 0.5, "formality": 0.7},
                "compassion": {"tone": "caring", "warmth": 0.9, "empathy": 0.9},
                "ennui": {"tone": "bland", "warmth": 0.3, "verbosity": 0.3},
            }

            if dominant in emotion_styles:
                style.update(emotion_styles[dominant])

            return style

    def get_emotion_distribution(self) -> Dict[str, float]:
        """获取当前情感分布

        Returns:
            情感分布字典
        """
        with self._lock:
            return self._emotion_state.copy()

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息

        Returns:
            统计信息字典
        """
        with self._lock:
            return {
                **self._stats,
                "agent_id": self._agent_id,
                "emotion_state": self._emotion_state.copy(),
                "history_count": len(self._emotion_history),
                "conduction_rules_count": len(self._conduction_rules),
            }

    def clear(self) -> None:
        """清空所有数据"""
        with self._lock:
            self._init_emotion_state()
            self._emotion_history.clear()
            self._stats = {
                "total_analyses": 0,
                "total_updates": 0,
                "dominant_emotion_changes": 0,
                "conduction_events": 0,
            }
            logger.info("EmotionHubEngine 数据已清空 (agent_id=%s)", self._agent_id)


# 全局实例管理
_emotion_hub_instances: Dict[str, EmotionHubEngine] = {}
_emotion_hub_lock = threading.Lock()


def get_emotion_hub_engine(agent_id: str = "default") -> EmotionHubEngine:
    """获取情感中枢引擎单例

    Args:
        agent_id: Agent标识符

    Returns:
        情感中枢引擎实例
    """
    global _emotion_hub_instances

    with _emotion_hub_lock:
        if agent_id not in _emotion_hub_instances:
            _emotion_hub_instances[agent_id] = EmotionHubEngine(agent_id=agent_id)
        return _emotion_hub_instances[agent_id]


def reset_emotion_hub_engine(agent_id: Optional[str] = None) -> None:
    """重置情感中枢引擎单例

    Args:
        agent_id: Agent标识符，为None时重置所有
    """
    global _emotion_hub_instances

    with _emotion_hub_lock:
        if agent_id is None:
            _emotion_hub_instances.clear()
        elif agent_id in _emotion_hub_instances:
            _emotion_hub_instances[agent_id].clear()
            del _emotion_hub_instances[agent_id]


def reset_all_emotion_hub_engines() -> None:
    """重置所有情感中枢引擎单例"""
    reset_emotion_hub_engine(None)
