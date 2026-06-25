"""
ClassifierModule — 记忆分类模块

对记忆进行分类和标签管理
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
    - 基于关键词的分类
    - 基于内容的标签提取
    - 分类规则管理
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._initialized = False

        # 分类规则: category -> keywords
        self._category_rules: Dict[str, List[str]] = {
            "personal": ["我", "我的", "个人", "自己", "my", "I", "me"],
            "work": ["工作", "项目", "任务", "会议", "work", "project", "task"],
            "knowledge": ["知识", "学习", "教程", "文档", "knowledge", "learn", "tutorial"],
            "conversation": ["对话", "聊天", "讨论", "chat", "conversation", "discuss"],
            "emotion": ["感觉", "心情", "情感", "feel", "emotion", "mood"],
            "technical": ["代码", "编程", "技术", "API", "code", "programming", "tech"],
        }

        # 记忆分类结果
        self._memory_categories: Dict[str, Set[str]] = {}  # memory_id -> categories
        self._memory_tags: Dict[str, Set[str]] = {}  # memory_id -> tags

    @property
    def name(self) -> str:
        """模块名称"""
        return "classifier_module"

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
        对记忆进行分类

        Args:
            memory_id: 记忆ID
            content: 记忆内容
            metadata: 额外元数据

        Returns:
            分类结果列表
        """
        categories = set()
        content_lower = content.lower()

        # 基于关键词分类
        for category, keywords in self._category_rules.items():
            for keyword in keywords:
                if keyword.lower() in content_lower:
                    categories.add(category)
                    break

        # 如果没有匹配任何分类，归为 general
        if not categories:
            categories.add("general")

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
        """添加分类规则"""
        with self._lock:
            if category in self._category_rules:
                self._category_rules[category].extend(keywords)
            else:
                self._category_rules[category] = keywords

    def remove_category_rule(self, category: str) -> bool:
        """移除分类规则"""
        with self._lock:
            return self._category_rules.pop(category, None) is not None

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
                "defined_categories": list(self._category_rules.keys()),
            }
