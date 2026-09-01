"""SemanticEmotionClassifier — 零样本（zero-shot）语义情感分类器

用文本嵌入与 8 条情感原型句的余弦相似度判定主情感，替代关键词规则。
关键词规则的"好"字效应（"你好"/"检查…功能" 被机械标成 joy）由此消除：
取决于相似度，而非词面命中。

设计约束：
- 编码器（encoder: text -> vector）由外部注入（复用 MoE 的 UnifiedVectorStore.encode），
  分类器本身不依赖 torch/onnx，纯数学；
- 不可用（无编码器 / 零向量 / 维度漂移）时 analyze() 返回 None，调用方降级规则引擎；
- 原型句向量按维度缓存，query 与原型维度不一致时视为不可用，绝不输出臆造情感。
"""

from __future__ import annotations

import math
import threading
from typing import Callable, Dict, List, Optional, Tuple

PROTOTYPE_TEXTS: Dict[str, str] = {
    "joy": "我今天特别开心，遇见了喜欢的事情，心情真的很好",
    "sadness": "我很难过，心里很悲伤，很失落，十分沮丧",
    "anger": "我非常生气，简直愤怒，无法容忍这么讨厌的事情",
    "fear": "我很害怕，非常担心，感到焦虑紧张不安",
    "surprise": "太意外了！我完全没想到，真是惊讶极了",
    "disgust": "我太反感了，觉得很恶心，令人厌恶",
    "trust": "我很信任他，完全相信，值得依靠",
    "neutral": "今天天气不错，我去市场买了些日常用品，一切如常",
}


def _cosine(a: List[float], b: List[float]) -> float:
    """余弦相似度（输入不保证归一化）"""
    if len(a) != len(b):
        raise ValueError("vector dim mismatch")
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _zero_norm(vec: List[float]) -> bool:
    return len(vec) == 0 or math.sqrt(sum(x * x for x in vec)) == 0


class SemanticEmotionClassifier:
    """zero-shot 情感分类器

    Attributes:
        threshold: 与最优原型的最小相似度，低于则判 neutral
        min_margin: 最优原型与第二名的差距下限，过低视为置信不足
        注意：余弦相似度对文本长度敏感度低但并非完美，阈值保守取 0.55。
    """

    def __init__(
        self,
        encoder: Optional[Callable[[str], List[float]]] = None,
        prototype_texts: Optional[Dict[str, str]] = None,
        threshold: float = 0.55,
        min_margin: float = 0.04,
    ):
        self._encoder = encoder
        self._prototype_texts = prototype_texts or PROTOTYPE_TEXTS
        self._threshold = threshold
        self._min_margin = min_margin
        self._prototype_vectors: Optional[Dict[str, List[float]]] = None
        self._prototype_dim: Optional[int] = None
        self._lock = threading.RLock()

    def set_encoder(self, encoder: Callable[[str], List[float]]) -> None:
        """更换/注入编码器（原型缓存会按维度失效重算）"""
        with self._lock:
            self._encoder = encoder
            self._prototype_vectors = None
            self._prototype_dim = None

    def _build_prototypes(self) -> bool:
        """编码全部原型句；任一失败/零向量 → 维持不可用（返回 False）"""
        if self._prototype_vectors is not None:
            return True
        if self._encoder is None:
            return False
        vectors: Dict[str, List[float]] = {}
        for emotion, text in self._prototype_texts.items():
            try:
                vec = self._encoder(text)
            except Exception:
                return False
            if _zero_norm(vec):
                return False
            if vectors and len(vec) != len(next(iter(vectors.values()))):
                return False  # 维度漂移（如 TF-IDF 词表增长），整体不可用
            vectors[emotion] = vec
        self._prototype_vectors = vectors
        self._prototype_dim = len(next(iter(vectors.values())))
        return True

    def analyze(self, text: str) -> Optional[Tuple[str, float]]:
        """返回 (primary_emotion, intensity) 或 None（视为 neutral/不可用）

        intensity 由相似度与 margin 综合映射到 [0.2, 1.0]，相似刚过阈值时最低。
        """
        if not text or not text.strip() or self._encoder is None:
            return None
        with self._lock:
            if not self._build_prototypes():
                return None
            try:
                vec = self._encoder(text)
            except Exception:
                return None
            if not vec or len(vec) != self._prototype_dim:
                return None

            sims = {e: _cosine(vec, p) for e, p in self._prototype_vectors.items()}
            top_emotion, top_sim = max(sims.items(), key=lambda kv: kv[1])
            second_sim = sorted(sims.values(), reverse=True)[1]

            if top_sim < self._threshold:
                return None
            if top_sim - second_sim < self._min_margin:
                return None
            if top_emotion == "neutral":
                # 最优原型为 neutral：视为无情感，不产出标注
                return None

            # 置信映射：距阈值 0 → 0.2；0.55→0.2，0.8 → 1.0
            intensity = min(1.0, max(0.2, (top_sim - self._threshold) / 0.25))
            return top_emotion, intensity
