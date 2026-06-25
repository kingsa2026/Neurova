from __future__ import annotations

"""
自动标签生成器 - Auto Tagger

从内容和来源自动生成标签。
"""

from neurova.core.logger import get_logger
import re
from typing import List, Set

from neurova.context.pool_models import ContextInput, ContextSource

logger = get_logger(__name__)


class AutoTagger:
    """自动标签生成器 - 从内容和来源自动生成标签"""

    SOURCE_TAGS = {
        ContextSource.SYSTEM_INSTRUCTION: ["系统", "指令"],
        ContextSource.DEVELOPER_INSTRUCTION: ["开发者", "指令"],
        ContextSource.MEMORY: ["记忆"],
        ContextSource.CONVERSATION: ["对话", "历史"],
        ContextSource.EXPERIENCE: ["经验", "知识"],
        ContextSource.EMOTION: ["情感", "心情"],
        ContextSource.REFLECTION: ["反思", "日志"],
        ContextSource.TOOL_CALL: ["工具", "调用"],
        ContextSource.MULTIMODAL: ["多模态", "媒体"],
        ContextSource.USER_INPUT: ["用户", "输入"],
    }

    KEYWORD_PATTERNS = {
        "编程": ["编程", "代码", "开发"],
        "代码": ["代码", "编程", "程序"],
        "Python": ["Python", "编程", "代码"],
        "机器学习": ["机器学习", "ML", "AI"],
        "深度学习": ["深度学习", "神经网络", "AI"],
        "优化": ["优化", "性能", "改进"],
        "调试": ["调试", "错误", "问题"],
        "测试": ["测试", "验证", "检查"],
        "部署": ["部署", "发布", "上线"],
        "数据库": ["数据库", "存储", "SQL"],
        "API": ["API", "接口", "服务"],
        "前端": ["前端", "UI", "界面"],
        "后端": ["后端", "服务", "服务端"],
    }

    def generate_tags(self, content: str) -> List[str]:
        if not content:
            return []

        tags = set()

        chinese_words = re.findall(r"[\u4e00-\u9fff]{2,4}", content)
        for word in chinese_words:
            if len(word) >= 2:
                tags.add(word)

        english_words = re.findall(r"[a-zA-Z]{3,}", content)
        for word in english_words:
            tags.add(word)

        for keyword, related_tags in self.KEYWORD_PATTERNS.items():
            if keyword in content:
                tags.update(related_tags)

        return list(tags)[:10]

    def generate_source_tags(self, source: ContextSource) -> List[str]:
        return self.SOURCE_TAGS.get(source, [])

    def merge_tags(self, existing_tags: List[str], new_tags: List[str]) -> List[str]:
        tag_set: Set[str] = set(existing_tags)
        tag_set.update(new_tags)
        return sorted(list(tag_set))

    def auto_tag(self, context: ContextInput) -> ContextInput:
        content_tags = self.generate_tags(context.content)
        source_tags = self.generate_source_tags(context.source)
        all_tags = self.merge_tags(context.tags, content_tags + source_tags)

        return ContextInput(
            source=context.source,
            content=context.content,
            priority=context.priority,
            metadata=context.metadata,
            tokens=context.tokens,
            tags=all_tags,
            hash=context.hash,
            created_at=context.created_at,
            updated_at=context.updated_at,
        )
