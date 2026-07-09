"""
EmotionModule — 情感模块

管理与记忆关联的情感状态，支持 SQLite 持久化。
"""

from __future__ import annotations

import json
from neurova.core.logger import get_logger
import sqlite3
import threading
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

    def __init__(self, emotion_weight: float = 0.3, db_path: Optional[str] = None):
        """
        Args:
            emotion_weight: 情感对记忆温度的影响权重
            db_path: SQLite 数据库路径（None 则仅内存）
        """
        self._emotion_weight = emotion_weight
        self._memory_emotions: Dict[str, EmotionState] = {}
        self._lock = threading.RLock()
        self._initialized = False
        self._db_path = db_path
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

    def analyze_text_emotion(self, text: str) -> EmotionState:
        """
        分析文本情感（简单规则实现）

        Args:
            text: 文本内容

        Returns:
            情感状态
        """
        text_lower = text.lower()

        # 简单的情感关键词匹配
        joy_words = ["高兴", "开心", "快乐", "喜欢", "好", "棒", "优秀", "happy", "joy", "good"]
        sadness_words = ["伤心", "难过", "失望", "遗憾", "sad", "sorry", "disappoint"]
        anger_words = ["生气", "愤怒", "讨厌", "烦", "angry", "hate", "annoying"]
        fear_words = ["害怕", "恐惧", "担心", "怕", "fear", "afraid", "worry"]
        surprise_words = ["惊讶", "意外", "没想到", "surprise", "unexpected", "wow"]

        # 计算各情感得分
        scores = {
            EmotionType.JOY: sum(1 for w in joy_words if w in text_lower),
            EmotionType.SADNESS: sum(1 for w in sadness_words if w in text_lower),
            EmotionType.ANGER: sum(1 for w in anger_words if w in text_lower),
            EmotionType.FEAR: sum(1 for w in fear_words if w in text_lower),
            EmotionType.SURPRISE: sum(1 for w in surprise_words if w in text_lower),
        }

        # 找到主要情感
        max_score = max(scores.values()) if scores else 0

        if max_score == 0:
            return EmotionState(
                primary_emotion=EmotionType.NEUTRAL,
                intensity=0.3,
                valence=0.0,
                arousal=0.3,
            )

        primary = max(scores, key=scores.get)

        # 计算效价和唤醒度
        valence_map = {
            EmotionType.JOY: 0.8,
            EmotionType.SADNESS: -0.6,
            EmotionType.ANGER: -0.7,
            EmotionType.FEAR: -0.5,
            EmotionType.SURPRISE: 0.3,
            EmotionType.NEUTRAL: 0.0,
        }

        arousal_map = {
            EmotionType.JOY: 0.6,
            EmotionType.SADNESS: 0.3,
            EmotionType.ANGER: 0.8,
            EmotionType.FEAR: 0.7,
            EmotionType.SURPRISE: 0.9,
            EmotionType.NEUTRAL: 0.2,
        }

        return EmotionState(
            primary_emotion=primary,
            intensity=min(1.0, max_score / 3),
            valence=valence_map.get(primary, 0.0),
            arousal=arousal_map.get(primary, 0.5),
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
