"""
EmotionModule — 情感模块

管理与记忆关联的情感状态，支持 SQLite 持久化。
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from neurova.core.logger import get_logger
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = get_logger(__name__)


class EmotionType(str, Enum):
    """情感类型"""

    JOY = "joy"
    SADNESS = "sadness"
    ANGER = "anger"
    FEAR = "fear"
    SURPRISE = "surprise"
    DISGUST = "disgust"
    TRUST = "trust"
    ANTICIPATION = "anticipation"
    NEUTRAL = "neutral"


@dataclass
class EmotionState:
    """情感状态"""

    primary_emotion: EmotionType
    intensity: float  # [0, 1]
    valence: float  # [-1, 1] 负面到正面
    arousal: float  # [0, 1] 平静到激动
    secondary_emotions: Dict[EmotionType, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "primary_emotion": self.primary_emotion.value,
            "intensity": self.intensity,
            "valence": self.valence,
            "arousal": self.arousal,
            "secondary_emotions": {k.value: v for k, v in self.secondary_emotions.items()},
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EmotionState":
        return cls(
            primary_emotion=EmotionType(data["primary_emotion"]),
            intensity=data.get("intensity", 0.5),
            valence=data.get("valence", 0.0),
            arousal=data.get("arousal", 0.5),
            secondary_emotions={EmotionType(k): v for k, v in data.get("secondary_emotions", {}).items()},
        )


class EmotionModule:
    """
    情感模块

    管理与记忆关联的情感状态，支持：
    - 情感标注
    - 情感检索
    - 情感影响记忆温度
    - SQLite 持久化
    """

    def __init__(
        self,
        emotion_weight: float = 0.3,
        db_path: Optional[str] = None,
        semantic_classifier: Optional[Any] = None,
    ):
        """
        Args:
            emotion_weight: 情感对记忆温度的影响权重
            db_path: SQLite 数据库路径（None 则仅内存）
            semantic_classifier: 语义情感分类器（嵌入 zero-shot），None 时纯规则引擎
        """
        self._emotion_weight = emotion_weight
        self._memory_emotions: Dict[str, EmotionState] = {}
        self._lock = threading.RLock()
        self._initialized = False
        self._db_path = db_path
        self._semantic_classifier = semantic_classifier
        self._conn: Optional[sqlite3.Connection] = None
        # 情感保护计数器（高强度情感触发保护机制时递增）
        self._protection_triggered: int = 0
        # Bug 14 修复: 移除重复的私有阈值 _emotional_protection_threshold,
        # 统一使用公开属性 emotional_protection_threshold(可被 RSI 调整)
        self.emotional_protection_threshold: float = 0.5  # RSI 可优化参数
        self.emotional_protection_factor: float = 0.3  # RSI 可优化参数

        if db_path:
            self._init_db()

    def _init_db(self) -> None:
        """初始化 SQLite 数据库"""
        try:
            self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS memory_emotions (
                    memory_id TEXT PRIMARY KEY,
                    emotion_data TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            self._conn.commit()

            # 从数据库加载到内存
            cursor = self._conn.execute("SELECT memory_id, emotion_data FROM memory_emotions")
            for row in cursor.fetchall():
                try:
                    data = json.loads(row[1])
                    self._memory_emotions[row[0]] = EmotionState.from_dict(data)
                except Exception as e:
                    # Bug 15 修复: 记录损坏记录的 warning,而非静默吞异常
                    logger.warning("跳过损坏的情感记录 %s: %s", row[0], e)

            logger.debug("EmotionModule DB loaded: %s emotions", len(self._memory_emotions))
        except Exception as e:
            logger.warning("EmotionModule DB init failed: %s", e)
            self._conn = None

    def _save_to_db(self, memory_id: str, emotion: EmotionState) -> None:
        """保存情感到数据库"""
        if not self._conn:
            return
        try:
            data = json.dumps(emotion.to_dict())
            self._conn.execute(
                """
                INSERT OR REPLACE INTO memory_emotions (memory_id, emotion_data, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
            """,
                (memory_id, data),
            )
            self._conn.commit()
        except Exception as e:
            logger.debug("EmotionModule DB save failed: %s", e)

    def _delete_from_db(self, memory_id: str) -> None:
        """从数据库删除情感"""
        if not self._conn:
            return
        try:
            self._conn.execute("DELETE FROM memory_emotions WHERE memory_id = ?", (memory_id,))
            self._conn.commit()
        except Exception as e:
            logger.debug("EmotionModule DB delete failed: %s", e)

    @property
    def name(self) -> str:
        """模块名称"""
        return "emotion_module"

    def init(self) -> bool:
        """初始化模块"""
        self._initialized = True
        logger.info("EmotionModule initialized")
        return True

    def shutdown(self) -> None:
        """关闭模块"""
        self._initialized = False
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
        logger.info("EmotionModule shutdown")

    def set_emotion(
        self,
        memory_id: str,
        emotion: EmotionState,
    ) -> None:
        """
        设置记忆的情感状态

        Args:
            memory_id: 记忆ID
            emotion: 情感状态
        """
        with self._lock:
            # 检查是否触发情感保护（高强度负面情感）
            # Bug 14 修复: 使用公开属性 emotional_protection_threshold(可被 RSI 调整),
            # 而非已移除的私有 _emotional_protection_threshold
            if emotion.intensity >= self.emotional_protection_threshold and emotion.valence < 0:
                self._protection_triggered += 1

            self._memory_emotions[memory_id] = emotion
            self._save_to_db(memory_id, emotion)

    def get_emotion(self, memory_id: str) -> Optional[EmotionState]:
        """获取记忆的情感状态"""
        with self._lock:
            return self._memory_emotions.get(memory_id)

    def set_semantic_classifier(self, classifier: Optional[Any]) -> None:
        """注入语义情感分类器（嵌入原型句 zero-shot）；不可用时自动降级规则引擎"""
        self._semantic_classifier = classifier

    def analyze_text_emotion(self, text: str) -> EmotionState:
        """
        分析文本情感（语义分类器优先，规则引擎兜底）

        语义路径：文本嵌入与 8 条情感原型句求余弦，取 argmax + 阈值，
        按语义判定而非词面命中，消除"好"字效应（如 "你好" 被标 joy）。
        规则路径：修正版关键词表（多字词 + 否定守卫 + ASCII 词边界）。
        """
        if self._semantic_classifier is not None:
            try:
                res = self._semantic_classifier.analyze(text)
                if res is not None:
                    primary, intensity = res
                    return EmotionState(
                        primary_emotion=EmotionType(primary),
                        intensity=round(float(intensity), 4),
                        valence=self._VALENCE_MAP.get(primary, 0.0),
                        arousal=self._AROUSAL_MAP.get(primary, 0.3),
                    )
            except Exception as e:
                logger.warning("语义情感分类失败，降级规则引擎: %s", e)
        return self._analyze_text_emotion_rules(text)

    # 效价/唤醒度表（语义与规则共用，中性不参与标注写入）
    _VALENCE_MAP = {
        "joy": 0.8, "sadness": -0.6, "anger": -0.7, "fear": -0.5,
        "surprise": 0.3, "disgust": -0.9, "neutral": 0.0,
    }
    _AROUSAL_MAP = {
        "joy": 0.6, "sadness": 0.3, "anger": 0.8, "fear": 0.7,
        "surprise": 0.9, "disgust": 0.8, "neutral": 0.2,
    }

    def _analyze_text_emotion_rules(self, text: str) -> EmotionState:
        """规则兜底：多字词词表 + 否定守卫 + ASCII 词边界

        刻意排除单字"好/棒/烦/怕"：关键词命中按整词（\b）扫描，
        "你好"/"检查网页搜索功能"/"麻烦你了"不再产生 joy/anger 误标。
        """
        text_lower = text.lower()

        # 否定守卫：消极短语直接判负，防 "不好/不开心/不高兴" 被 joy 词表击中
        if any(kw in text_lower for kw in ("不好", "不开心", "不高兴", "不喜欢", "糟透", "太难过了")):
            return EmotionState(
                primary_emotion=EmotionType.SADNESS,
                intensity=0.5,
                valence=self._VALENCE_MAP["sadness"],
                arousal=self._AROUSAL_MAP["sadness"],
            )

        # 多字词为主；ASCII 词走整词匹配
        _WORD_TABLES = {
            "joy": (["开心", "高兴", "快乐", "喜悦", "兴奋", "太好了", "真好", "很好",
                     "优秀", "喜欢", "棒极了", "欢乐", "愉快", "幸福", "幸运", "期待"],
                    ["happy", "joy", "excited", "great", "glad", "cheerful", "love"]),
            "sadness": (["难过", "伤心", "悲伤", "沮丧", "忧郁", "失落", "痛苦", "遗憾", "失望", "想哭"],
                        ["sad", "sorry", "disappointed", "depressed", "unhappy", "sorrow"]),
            "anger": (["生气", "愤怒", "恼怒", "气愤", "暴怒", "讨厌", "可恶", "火大", "发脾气", "气死"],
                      ["angry", "hate", "mad", "furious", "annoyed"]),
            "fear": (["害怕", "恐惧", "担心", "焦虑", "紧张", "惊慌", "吓人", "可怕", "不安"],
                     ["afraid", "fear", "worry", "anxious", "panic", "scared"]),
            "surprise": (["惊讶", "震惊", "吃惊", "意外", "没想到", "惊呆了", "惊喜"],
                         ["surprise", "unexpected", "amazed", "shock", "wow"]),
            "disgust": (["恶心", "反感", "厌恶", "嫌弃", "呕吐"],
                        ["disgust", "repulse", "yuck", "gross"]),
        }

        scores = {}
        for emotion, (cn_words, en_words) in _WORD_TABLES.items():
            score = sum(1 for w in cn_words if w in text_lower)
            score += sum(1 for w in en_words if re.search(r"\b" + re.escape(w) + r"\b", text_lower))
            scores[emotion] = score

        max_score = max(scores.values()) if scores else 0

        if max_score == 0:
            return EmotionState(
                primary_emotion=EmotionType.NEUTRAL,
                intensity=0.3,
                valence=0.0,
                arousal=0.3,
            )

        primary = max(scores, key=scores.get)
        return EmotionState(
            primary_emotion=EmotionType(primary),
            intensity=min(1.0, max_score / 3),
            valence=self._VALENCE_MAP.get(primary, 0.0),
            arousal=self._AROUSAL_MAP.get(primary, 0.5),
        )

    def get_emotional_memories(
        self,
        emotion_type: Optional[EmotionType] = None,
        min_intensity: float = 0.5,
        limit: int = 10,
    ) -> List[str]:
        """
        获取带有特定情感的记忆

        Args:
            emotion_type: 情感类型过滤
            min_intensity: 最低强度
            limit: 返回数量限制

        Returns:
            记忆ID列表
        """
        with self._lock:
            results = []

            for memory_id, emotion in self._memory_emotions.items():
                if emotion_type and emotion.primary_emotion != emotion_type:
                    continue

                if emotion.intensity < min_intensity:
                    continue

                results.append((memory_id, emotion.intensity))

            # 按强度排序
            results.sort(key=lambda x: x[1], reverse=True)
            return [mid for mid, _ in results[:limit]]

    def get_temperature_modifier(self, memory_id: str) -> float:
        """
        获取情感对温度的修正值

        Args:
            memory_id: 记忆ID

        Returns:
            温度修正值 [-emotion_weight, emotion_weight]
        """
        emotion = self.get_emotion(memory_id)
        if emotion is None:
            return 0.0

        # 正面情感提高温度，负面情感降低温度
        return emotion.valence * self._emotion_weight * emotion.intensity

    def remove_emotion(self, memory_id: str) -> bool:
        """移除记忆的情感标注"""
        with self._lock:
            result = self._memory_emotions.pop(memory_id, None) is not None
            if result:
                self._delete_from_db(memory_id)
            return result

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._lock:
            if not self._memory_emotions:
                return {
                    "total_annotated": 0,
                    "emotion_distribution": {},
                }

            # 统计情感分布
            distribution = {}
            for emotion in self._memory_emotions.values():
                emo_type = emotion.primary_emotion.value
                distribution[emo_type] = distribution.get(emo_type, 0) + 1

            return {
                "total_annotated": len(self._memory_emotions),
                "emotion_distribution": distribution,
                "emotion_weight": self._emotion_weight,
            }

    def get_feedback(self) -> Dict[str, Any]:
        """
        获取情感模块的反馈信号，供 RSI 系统使用。

        Returns:
            Dict[str, Any]: 包含 emotional_memories, avg_intensity, protection_triggered
        """
        with self._lock:
            emotional_memories = len(self._memory_emotions)
            if emotional_memories > 0:
                avg_intensity = sum(e.intensity for e in self._memory_emotions.values()) / emotional_memories
            else:
                avg_intensity = 0.0

            return {
                "emotional_memories": emotional_memories,
                "avg_intensity": avg_intensity,
                "protection_triggered": self._protection_triggered,
            }
