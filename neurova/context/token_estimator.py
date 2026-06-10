"""
统一 Token 估算器

解决 token 估算不一致问题：
1. injector.py - _count_tokens (chinese_ratio=1.5, english_ratio=0.25)
2. context_pool.py - ContextPoolUtils.estimate_tokens (中文1.5, 英文0.25)
3. context_compressor.py - Message.estimate_tokens (中文2, 英文1)
4. context_compressor.py - len() // 4 (粗略估算)

提供统一的估算接口，支持多种策略。
"""

import re
from typing import Optional
from enum import Enum


class EstimationStrategy(Enum):
    """估算策略"""
    BALANCED = "balanced"           # 平衡策略（推荐）
    CONSERVATIVE = "conservative"   # 保守策略（高估）
    AGGRESSIVE = "aggressive"       # 激进策略（低估）
    LEGACY_INJECTOR = "legacy_injector"   # 兼容 injector.py
    LEGACY_POOL = "legacy_pool"           # 兼容 context_pool.py
    LEGACY_COMPRESSOR = "legacy_compressor" # 兼容 context_compressor.py
    LEGACY_ROUGH = "legacy_rough"         # 兼容 len() // 4


class TokenEstimator:
    """
    统一的 Token 估算器
    
    提供一致的 token 估算接口，支持多种策略。
    """
    
    def __init__(self, strategy: EstimationStrategy = EstimationStrategy.BALANCED):
        """
        初始化估算器
        
        Args:
            strategy: 估算策略
        """
        self.strategy = strategy
        self._load_strategy(strategy)
    
    def _load_strategy(self, strategy: EstimationStrategy):
        """加载策略配置"""
        if strategy == EstimationStrategy.BALANCED:
            # 平衡策略：兼顾精度和性能
            self.chinese_ratio = 1.5
            self.english_word_ratio = 0.25
            self.other_char_ratio = 0.1
            self.min_tokens = 1
            self.use_word_splitting = True
            self.use_regex_splitting = False
            
        elif strategy == EstimationStrategy.CONSERVATIVE:
            # 保守策略：高估 token 数，避免超出预算
            self.chinese_ratio = 2.0
            self.english_word_ratio = 0.5
            self.other_char_ratio = 0.2
            self.min_tokens = 1
            self.use_word_splitting = True
            self.use_regex_splitting = False
            
        elif strategy == EstimationStrategy.AGGRESSIVE:
            # 激进策略：低估 token 数，尽可能多地包含内容
            self.chinese_ratio = 1.0
            self.english_word_ratio = 0.2
            self.other_char_ratio = 0.05
            self.min_tokens = 0
            self.use_word_splitting = True
            self.use_regex_splitting = False
            
        elif strategy == EstimationStrategy.LEGACY_INJECTOR:
            # 兼容 injector.py 的旧算法
            self.chinese_ratio = 1.5
            self.english_word_ratio = None  # 不使用单词分割
            self.other_char_ratio = 0.25
            self.min_tokens = 0
            self.use_word_splitting = False
            self.use_regex_splitting = False
            
        elif strategy == EstimationStrategy.LEGACY_POOL:
            # 兼容 context_pool.py 的旧算法
            self.chinese_ratio = 1.5
            self.english_word_ratio = 0.25
            self.other_char_ratio = None  # 不计算其他字符
            self.min_tokens = 1
            self.use_word_splitting = True
            self.use_regex_splitting = False
            
        elif strategy == EstimationStrategy.LEGACY_COMPRESSOR:
            # 兼容 context_compressor.py Message.estimate_tokens 的旧算法
            self.chinese_ratio = 2.0
            self.english_word_ratio = 1.0
            self.other_char_ratio = None  # 不计算其他字符
            self.min_tokens = 0
            self.use_word_splitting = False
            self.use_regex_splitting = True
            
        elif strategy == EstimationStrategy.LEGACY_ROUGH:
            # 兼容 len() // 4 的粗略估算
            self.chinese_ratio = 0.25  # 每个字符 0.25 token
            self.english_word_ratio = None
            self.other_char_ratio = 0.25
            self.min_tokens = 0
            self.use_word_splitting = False
            self.use_regex_splitting = False
    
    def estimate(self, text: str) -> int:
        """
        估算文本的 token 数量
        
        Args:
            text: 要估算的文本
            
        Returns:
            估算的 token 数量
        """
        if not text:
            return 0
        
        # 中文字符计数
        chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        
        # 计算中文 token 数
        chinese_tokens = chinese_chars * self.chinese_ratio
        
        # 计算英文和其他 token 数
        if self.use_regex_splitting:
            # 使用正则表达式分割（兼容 context_compressor.py）
            english_words = len(re.findall(r'[a-zA-Z]+', text))
            english_tokens = english_words * self.english_word_ratio if self.english_word_ratio else 0
            other_tokens = 0  # 正则模式不单独计算其他字符
        elif self.use_word_splitting:
            # 使用空格分割（兼容 context_pool.py）
            words = text.split()
            english_words = len(words)
            english_tokens = english_words * self.english_word_ratio if self.english_word_ratio else 0
            other_tokens = 0  # 单词分割模式不单独计算其他字符
        else:
            # 使用字符计数（兼容 injector.py 和 len() // 4）
            other_chars = len(text) - chinese_chars
            english_tokens = 0
            other_tokens = other_chars * self.other_char_ratio if self.other_char_ratio else 0
        
        # 计算总 token 数
        total = chinese_tokens + english_tokens + other_tokens
        
        # 应用最小值
        total = max(self.min_tokens, total)
        
        return int(total)
    
    def estimate_batch(self, texts: list) -> list:
        """
        批量估算 token 数量
        
        Args:
            texts: 文本列表
            
        Returns:
            token 数量列表
        """
        return [self.estimate(text) for text in texts]
    
    def get_strategy_info(self) -> dict:
        """
        获取当前策略的详细信息
        
        Returns:
            策略信息字典
        """
        return {
            'strategy': self.strategy.value,
            'chinese_ratio': self.chinese_ratio,
            'english_word_ratio': self.english_word_ratio,
            'other_char_ratio': self.other_char_ratio,
            'min_tokens': self.min_tokens,
            'use_word_splitting': self.use_word_splitting,
            'use_regex_splitting': self.use_regex_splitting,
        }


# 全局默认估算器实例
_default_estimator: Optional[TokenEstimator] = None


def get_token_estimator(strategy: EstimationStrategy = EstimationStrategy.BALANCED) -> TokenEstimator:
    """
    获取 Token 估算器实例
    
    Args:
        strategy: 估算策略
        
    Returns:
        TokenEstimator 实例
    """
    global _default_estimator
    
    if _default_estimator is None or _default_estimator.strategy != strategy:
        _default_estimator = TokenEstimator(strategy)
    
    return _default_estimator


def estimate_tokens(text: str, strategy: EstimationStrategy = EstimationStrategy.BALANCED) -> int:
    """
    估算文本的 token 数量（便捷函数）
    
    Args:
        text: 要估算的文本
        strategy: 估算策略
        
    Returns:
        估算的 token 数量
    """
    estimator = get_token_estimator(strategy)
    return estimator.estimate(text)


# 向后兼容的接口
class ContextPoolUtils:
    """兼容 context_pool.py 的工具类"""
    
    @staticmethod
    def estimate_tokens(text: str) -> int:
        """估算 token 数量（使用平衡策略）"""
        return estimate_tokens(text, EstimationStrategy.BALANCED)