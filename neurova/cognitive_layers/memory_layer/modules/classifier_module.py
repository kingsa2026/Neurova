"""
ClassifierModule — 记忆分类模块（分类缓存 / 标签面）

职责边界（2026-09-21 收敛，Issue #68）：
- **分类推断**不再在本文件实现。本文件此前自带 6 个硬编码关键词桶
  （personal/work/knowledge/conversation/emotion/technical），与
  `MemoryCategory`（7 值）**同名不同集且数量不同**：`general` 只是在
  兜底分支里被 append，`experience`/`reflection`/`user_preference`/
  `tool_usage` 四个生产枚举值根本认不出来。那条规则表是分叉的第二源头，
  已删除。现统一委托 `auto_classifier.MemoryAutoClassifier`（唯一引擎）。
- 本模块保留**有状态**的部分：memory_id → categories / tags 缓存与检索。
  标签抽取（引号 / @ / # / 长词）是独立能力，不属于分类引擎，留在本文件。

实现细节：classification 走引擎，缓存写入仍按 memory_id 索引，供
`get_categories` / `search_by_category` / `get_stats` 消费。
"""

from __future__ import annotations

from neurova.core.logger import get_logger
import re
import threading
from typing import Any, Dict, List, Optional, Set

logger = get_logger(__name__)


class ClassifierModule:
    """
    记忆分类模块

    对记忆进行自动分类和标签管理，支持：
    - 基于关键词的分类（委托 `MemoryAutoClassifier`，词汇表 = models.py）
    - 基于内容的标签提取
    - 分类缓存与检索（by category / by tag）
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._initialized = False

        # 分类引擎（懒加载，避免模块导入期的重初始化）
        self._engine = None

        # 记忆分类结果
        self._memory_categories: Dict[str, Set[str]] = {}  # memory_id -> categories
        self._memory_tags: Dict[str, Set[str]] = {}  # memory_id -> tags

    @property
    def name(self) -> str:
        """模块名称"""
        return "classifier_module"

    def _ensure_engine(self):
        """懒加载唯一分类引擎（分类词汇表的定义在 models.py，不在此处）"""
        if self._engine is None:
            from neurova.cognitive_layers.memory_layer.auto_classifier import (
                MemoryAutoClassifier,
            )

            self._engine = MemoryAutoClassifier()
        return self._engine

    @property
    def defined_categories(self) -> List[str]:
        """本模块可能产出的分类全集（= MemoryCategory 枚举值，无第二套）。"""
        from neurova.cognitive_layers.memory_layer.models import MemoryCategory

        return [c.value for c in MemoryCategory]

    def init(self) -> bool:
        """初始化模块"""
        self._initialized = True
        logger.info("ClassifierModule initialized")
        return True

    def shutdown(self) -> None:
        """关闭模块"""
        self._initialized = False
        logger.info("ClassifierModule shutdown")

    def classify(
        self,
        memory_id: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
        """
        对记忆进行分类（多标签，值域 = MemoryCategory）

        Args:
            memory_id: 记忆ID
            content: 记忆内容
            metadata: 额外元数据

        Returns:
            分类结果列表（至少含一个值；命中多个关键词桶时全部返回，
            由调用方决定取最佳还是全取）
        """
        engine = self._ensure_engine()
        result = engine.classify(content, metadata)
        categories = {result["category"].value}
        for cat, _score in result["details"].get("category_multi_label", []):
            categories.add(cat.value)

        with self._lock:
            self._memory_categories[memory_id] = categories

        return list(categories)

    def extract_tags(
        self,
        memory_id: str,
        content: str,
        max_tags: int = 10,
    ) -> List[str]:
        """
        提取标签

        Args:
            memory_id: 记忆ID
            content: 内容
            max_tags: 最大标签数

        Returns:
            标签列表
        """
        tags = set()

        # 提取引号中的内容作为标签
        quoted = re.findall(r'["\'](.*?)["\']', content)
        tags.update(quoted[:3])

        # 提取 @ 标记
        at_mentions = re.findall(r"@(\w+)", content)
        tags.update(at_mentions[:3])

        # 提取 # 标签
        hashtags = re.findall(r"#(\w+)", content)
        tags.update(hashtags[:3])

        # 提取关键名词（简单实现）
        words = content.split()
        important_words = [w for w in words if len(w) >= 3 and not w.startswith((".", ",", "!", "?"))]
        tags.update(important_words[: max_tags - len(tags)])

        with self._lock:
            self._memory_tags[memory_id] = tags

        return list(tags)[:max_tags]

    def add_category_rule(self, category: str, keywords: List[str]) -> None:
        """添加分类关键词（透传到唯一引擎，不再维护第二份规则表）

        非法分类名显式拒绝：此前任意字符串都能建桶（于是库里出现
        personal/work/technical 等无对应 MemoryCategory 的分类），
        现要求必须是 MemoryCategory 枚举值。
        """
        from neurova.cognitive_layers.memory_layer.models import MemoryCategory

        try:
            MemoryCategory(category)
        except (ValueError, KeyError) as exc:
            raise ValueError(
                f"未知分类 '{category}'：分类值域 = MemoryCategory 枚举（{self.defined_categories}）"
            ) from exc

        self._ensure_engine().add_category_keywords(category, keywords)

    def get_categories(self, memory_id: str) -> List[str]:
        """获取记忆的分类"""
        with self._lock:
            return list(self._memory_categories.get(memory_id, set()))

    def get_tags(self, memory_id: str) -> List[str]:
        """获取记忆的标签"""
        with self._lock:
            return list(self._memory_tags.get(memory_id, set()))

    def search_by_category(
        self,
        category: str,
        limit: int = 10,
    ) -> List[str]:
        """按分类搜索记忆"""
        with self._lock:
            results = []
            for memory_id, categories in self._memory_categories.items():
                if category in categories:
                    results.append(memory_id)
            return results[:limit]

    def search_by_tag(
        self,
        tag: str,
        limit: int = 10,
    ) -> List[str]:
        """按标签搜索记忆"""
        with self._lock:
            results = []
            for memory_id, tags in self._memory_tags.items():
                if tag in tags:
                    results.append(memory_id)
            return results[:limit]

    def remove_memory(self, memory_id: str) -> None:
        """移除记忆的分类和标签"""
        with self._lock:
            self._memory_categories.pop(memory_id, None)
            self._memory_tags.pop(memory_id, None)

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._lock:
            category_counts = {}
            for categories in self._memory_categories.values():
                for cat in categories:
                    category_counts[cat] = category_counts.get(cat, 0) + 1

            tag_counts = {}
            for tags in self._memory_tags.values():
                for tag in tags:
                    tag_counts[tag] = tag_counts.get(tag, 0) + 1

            return {
                "total_classified": len(self._memory_categories),
                "total_tagged": len(self._memory_tags),
                "category_distribution": category_counts,
                "top_tags": sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)[:20],
                "defined_categories": self.defined_categories,
            }
