"""
指代消解器

解决代词/同义词问题，将 "它"、"这个" 链接到具体实体。
"""

import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class CoreferenceResolver:
    """指代消解器"""
    
    PRONOUN_PATTERNS = {
        "它": ["数据库", "服务器", "API", "缓存", "队列", "系统", "模块"],
        "这个": ["系统", "模块", "组件", "接口", "功能", "配置"],
        "那个": ["服务", "功能", "配置", "工具", "方法"],
        "他们": ["团队", "开发者", "管理员", "用户"],
        "它们": ["数据库", "服务器", "API", "组件", "模块"],
    }
    
    def __init__(self, memory_manager=None):
        """
        初始化指代消解器
        
        Args:
            memory_manager: 记忆管理器（可选）
        """
        self.memory_manager = memory_manager
        self.entity_cache: Dict[str, List[str]] = {}
        logger.info("CoreferenceResolver 初始化完成")
    
    def resolve(
        self, 
        text: str, 
        recent_entities: List[str],
        context_window: int = 3
    ) -> str:
        """
        将文本中的代词替换为具体实体
        
        Args:
            text: 原始文本
            recent_entities: 最近提到的实体列表
            context_window: 上下文窗口大小
            
        Returns:
            替换后的文本
        """
        if not text:
            return text
        
        resolved_text = text
        
        # 1. 代词替换
        for pronoun, candidates in self.PRONOUN_PATTERNS.items():
            if pronoun in resolved_text:
                # 从最近实体中找到匹配的候选
                best_match = self._find_best_match(
                    pronoun, candidates, recent_entities[:context_window]
                )
                if best_match:
                    resolved_text = resolved_text.replace(pronoun, best_match, 1)
        
        # 2. 同义词合并
        resolved_text = self._merge_synonyms(resolved_text)
        
        return resolved_text
    
    def _find_best_match(
        self, 
        pronoun: str, 
        candidates: List[str],
        recent_entities: List[str]
    ) -> Optional[str]:
        """
        找到最佳匹配实体
        
        优先使用最近提到的实体。
        
        Args:
            pronoun: 代词
            candidates: 候选实体列表
            recent_entities: 最近提到的实体列表
            
        Returns:
            最佳匹配实体，如果没有匹配返回None
        """
        # 优先使用最近提到的实体
        for entity in reversed(recent_entities):
            if entity in candidates:
                return entity
        
        # 如果最近实体中没有匹配，返回第一个候选
        return candidates[0] if candidates else None
    
    def _merge_synonyms(self, text: str) -> str:
        """
        同义词合并
        
        将常见的同义词替换为标准形式。
        """
        # 简单的同义词映射
        synonyms = {
            "数据库": ["DB", "db", "database"],
            "服务器": ["server", "主机"],
            "API": ["api", "接口"],
            "缓存": ["cache", "Redis", "redis"],
        }
        
        resolved = text
        for standard, alts in synonyms.items():
            for alt in alts:
                if alt in resolved and alt != standard:
                    resolved = resolved.replace(alt, standard, 1)
        
        return resolved
    
    def add_entity(self, entity: str):
        """添加实体到缓存"""
        if entity not in self.entity_cache:
            self.entity_cache[entity] = []
        self.entity_cache[entity].append(entity)
    
    def get_recent_entities(self, limit: int = 10) -> List[str]:
        """获取最近的实体"""
        all_entities = []
        for entities in self.entity_cache.values():
            all_entities.extend(entities)
        return all_entities[-limit:]
