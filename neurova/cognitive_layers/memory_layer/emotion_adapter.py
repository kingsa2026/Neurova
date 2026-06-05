"""
情感分析器适配器 - 兼容情感中枢引擎 v1.0.0

这个模块提供向后兼容的接口，让现有代码能够平滑过渡到新的四层情感分类体系。
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class EmotionAnalyzerAdapter:
    """
    情感分析器适配器
    
    提供向后兼容的接口，让现有代码能够平滑过渡到新的四层情感分类体系。
    """
    
    def __init__(self, use_legacy: bool = False):
        """
        初始化适配器
        
        Args:
            use_legacy: 是否使用旧版算法
        """
        self._use_legacy = use_legacy
        self._analyzer = None
        
        # 延迟初始化，避免循环导入
        logger.info("EmotionAnalyzerAdapter 初始化完成")
    
    def _get_analyzer(self):
        """获取情感分析器（延迟初始化）"""
        if self._analyzer is None:
            try:
                from .emotion import get_emotion_analyzer_instance
                self._analyzer = get_emotion_analyzer_instance()
            except ImportError:
                logger.warning("无法导入情感分析器，使用简化版本")
                self._analyzer = self._create_simple_analyzer()
        
        return self._analyzer
    
    def _create_simple_analyzer(self):
        """创建简单的情感分析器"""
        # 简单实现，当无法导入完整分析器时使用
        class SimpleAnalyzer:
            def analyze(self, text: str, context=None):
                return {
                    "primary_emotion": "neutral",
                    "confidence": 0.0,
                    "emotions": {},
                    "tags": [],
                    "score": 0.0,
                }
            
            def batch_analyze(self, texts, contexts=None):
                return [self.analyze(t) for t in texts]
            
            def get_emotion_tags(self, emotion_scores, threshold=0.3):
                return []
            
            def get_emotion_score(self, text, target_emotion):
                return 0.0
            
            def get_detailed_scores(self, text):
                return {}
            
            def get_emotion_hierarchy(self):
                return {}
            
            def get_emotion_stats(self, texts):
                return {}
            
            def get_emotion_distribution(self, texts):
                return {}
        
        return SimpleAnalyzer()
    
    def analyze(self, text: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        分析文本的情感
        
        Args:
            text: 要分析的文本
            context: 可选的上下文信息
            
        Returns:
            情感分析结果
        """
        analyzer = self._get_analyzer()
        
        if self._use_legacy:
            return self._analyze_legacy(text, context)
        
        return analyzer.analyze(text, context)
    
    def _analyze_legacy(self, text: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """旧版简单情感分析"""
        # 简单的关键词匹配
        positive_words = ["开心", "快乐", "高兴", "喜悦", "兴奋", "happy", "joy", "excited"]
        negative_words = ["悲伤", "难过", "伤心", "沮丧", "sad", "unhappy", "depressed"]
        
        text_lower = text.lower()
        
        positive_count = sum(1 for word in positive_words if word.lower() in text_lower)
        negative_count = sum(1 for word in negative_words if word.lower() in text_lower)
        
        if positive_count > negative_count:
            primary_emotion = "joy"
            confidence = min(positive_count * 0.2, 1.0)
            score = confidence
        elif negative_count > positive_count:
            primary_emotion = "sadness"
            confidence = min(negative_count * 0.2, 1.0)
            score = -confidence
        else:
            primary_emotion = "neutral"
            confidence = 0.0
            score = 0.0
        
        return {
            "primary_emotion": primary_emotion,
            "confidence": confidence,
            "emotions": {primary_emotion: confidence},
            "tags": [primary_emotion] if primary_emotion != "neutral" else [],
            "score": score,
        }
    
    def batch_analyze(self, texts: List[str], contexts: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
        """
        批量分析多个文本的情感
        
        Args:
            texts: 文本列表
            contexts: 可选的上下文列表
            
        Returns:
            分析结果列表
        """
        analyzer = self._get_analyzer()
        return analyzer.batch_analyze(texts, contexts)
    
    def get_emotion_tags(self, emotion_scores: Dict[str, float], threshold: float = 0.3) -> List[str]:
        """
        获取情感标签
        
        Args:
            emotion_scores: 情感分数字典
            threshold: 标签阈值
            
        Returns:
            情感标签列表
        """
        analyzer = self._get_analyzer()
        return analyzer.get_emotion_tags(emotion_scores, threshold)
    
    def get_emotion_score(self, text: str, target_emotion: str) -> float:
        """
        获取文本对特定情感的分数
        
        Args:
            text: 文本
            target_emotion: 目标情感
            
        Returns:
            情感分数
        """
        analyzer = self._get_analyzer()
        return analyzer.get_emotion_score(text, target_emotion)
    
    def get_detailed_scores(self, text: str) -> Dict[str, Dict[str, Any]]:
        """
        获取详细的情感分数信息
        
        Args:
            text: 文本
            
        Returns:
            包含详细信息的情感分数字典
        """
        analyzer = self._get_analyzer()
        return analyzer.get_detailed_scores(text)
    
    def get_emotion_hierarchy(self) -> Dict[str, Dict[str, Any]]:
        """
        获取情感层次结构
        
        Returns:
            情感层次结构字典
        """
        analyzer = self._get_analyzer()
        return analyzer.get_emotion_hierarchy()
    
    def get_emotion_stats(self, texts: List[str]) -> Dict[str, Any]:
        """
        获取多个文本的情感统计信息
        
        Args:
            texts: 文本列表
            
        Returns:
            统计信息字典
        """
        analyzer = self._get_analyzer()
        return analyzer.get_emotion_stats(texts)
    
    def get_emotion_distribution(self, texts: List[str]) -> Dict[str, float]:
        """
        获取多个文本的情感分布
        
        Args:
            texts: 文本列表
            
        Returns:
            情感分布字典
        """
        analyzer = self._get_analyzer()
        return analyzer.get_emotion_distribution(texts)


# 全局实例
_adapter: Optional[EmotionAnalyzerAdapter] = None


def get_emotion_analyzer(use_legacy: bool = False) -> EmotionAnalyzerAdapter:
    """
    获取情感分析器（工厂函数）
    
    Args:
        use_legacy: 是否使用旧版算法
        
    Returns:
        情感分析器适配器
    """
    global _adapter
    
    if _adapter is None:
        _adapter = EmotionAnalyzerAdapter(use_legacy=use_legacy)
    
    return _adapter