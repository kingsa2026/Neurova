"""
Emotion Analyzer v1.0.0 - 基于情感中枢引擎

提供情感分析功能，用于分析记忆的情感分数和标签。
支持四层17种情感分类体系。
"""

import logging
import re
import threading
from typing import Dict, List, Optional, Tuple, Any

logger = logging.getLogger(__name__)

# 四层17种情感分类体系
_EMOTION_HIERARCHY = {
    # 第一层：基础情感（Primary Emotions）
    "joy": {"layer": 1, "category": "positive", "intensity_range": (0.1, 1.0)},
    "sadness": {"layer": 1, "category": "negative", "intensity_range": (0.1, 1.0)},
    "anger": {"layer": 1, "category": "negative", "intensity_range": (0.1, 1.0)},
    "fear": {"layer": 1, "category": "negative", "intensity_range": (0.1, 1.0)},
    "surprise": {"layer": 1, "category": "neutral", "intensity_range": (0.1, 1.0)},
    "disgust": {"layer": 1, "category": "negative", "intensity_range": (0.1, 1.0)},
    
    # 第二层：次级情感（Secondary Emotions）
    "trust": {"layer": 2, "category": "positive", "intensity_range": (0.2, 0.8)},
    "anticipation": {"layer": 2, "category": "positive", "intensity_range": (0.2, 0.8)},
    "confusion": {"layer": 2, "category": "negative", "intensity_range": (0.2, 0.8)},
    "frustration": {"layer": 2, "category": "negative", "intensity_range": (0.2, 0.8)},
    
    # 第三层：复合情感（Complex Emotions）
    "love": {"layer": 3, "category": "positive", "intensity_range": (0.3, 1.0)},
    "gratitude": {"layer": 3, "category": "positive", "intensity_range": (0.3, 0.9)},
    "nostalgia": {"layer": 3, "category": "mixed", "intensity_range": (0.3, 0.8)},
    "anxiety": {"layer": 3, "category": "negative", "intensity_range": (0.3, 0.9)},
    
    # 第四层：元情感（Meta-Emotions）
    "pride": {"layer": 4, "category": "positive", "intensity_range": (0.4, 1.0)},
    "shame": {"layer": 4, "category": "negative", "intensity_range": (0.4, 1.0)},
    "empathy": {"layer": 4, "category": "positive", "intensity_range": (0.4, 0.9)},
}

# 情感关键词映射
_EMOTION_KEYWORDS = {
    "joy": ["happy", "joyful", "excited", "pleased", "delighted", "cheerful", "glad", "elated", "开心", "快乐", "高兴", "喜悦", "兴奋"],
    "sadness": ["sad", "unhappy", "depressed", "melancholy", "gloomy", "sorrowful", "悲伤", "难过", "伤心", "沮丧", "忧郁"],
    "anger": ["angry", "furious", "rage", "irritated", "annoyed", "mad", "愤怒", "生气", "恼怒", "暴怒", "气愤"],
    "fear": ["afraid", "fearful", "scared", "terrified", "anxious", "worried", "nervous", "恐惧", "害怕", "担心", "焦虑", "紧张"],
    "surprise": ["surprised", "astonished", "amazed", "shocked", "stunned", "惊讶", "震惊", "吃惊", "意外"],
    "disgust": ["disgusted", "repulsed", "revolted", "sickened", "厌恶", "恶心", "反感", "嫌弃"],
    "trust": ["trust", "believe", "confide", "rely", "depend", "信任", "相信", "信赖", "依赖"],
    "anticipation": ["anticipate", "expect", "look forward", "await", "期待", "盼望", "期望", "等待"],
    "confusion": ["confused", "puzzled", "perplexed", "bewildered", "lost", "困惑", "迷惑", "迷茫", "不解"],
    "frustration": ["frustrated", "disappointed", "discouraged", "let down", "挫折", "失望", "沮丧", "挫败"],
    "love": ["love", "adore", "cherish", "affection", "fond", "爱", "热爱", "喜爱", "钟爱", "喜欢"],
    "gratitude": ["grateful", "thankful", "appreciate", "obliged", "感激", "感谢", "感恩", "谢意"],
    "nostalgia": ["nostalgic", "reminiscent", "sentimental", "怀旧", "怀念", "思念", "回忆"],
    "anxiety": ["anxious", "worried", "uneasy", "apprehensive", "焦虑", "不安", "担忧", "忧虑"],
    "pride": ["proud", "accomplished", "satisfied", "triumphant", "自豪", "骄傲", "得意", "满足"],
    "shame": ["ashamed", "embarrassed", "humiliated", "mortified", "羞耻", "尴尬", "羞愧", "惭愧"],
    "empathy": ["empathize", "understand", "compassion", "sympathize", "共情", "理解", "同情", "体谅"],
}


class EmotionAnalyzer:
    """
    情感分析器
    
    提供四层17种情感分类体系的分析功能。
    支持文本情感分析、情感标签提取、情感分数计算等。
    """
    
    def __init__(self, use_legacy: bool = False):
        """
        初始化情感分析器
        
        Args:
            use_legacy: 是否使用旧版简单关键词匹配算法
        """
        self._lock = threading.RLock()
        self._use_legacy = use_legacy
        self._compiled_patterns: Dict[str, List[re.Pattern]] = {}
        self._compile_patterns()
        logger.info("EmotionAnalyzer 初始化完成")
    
    def _compile_patterns(self):
        """预编译情感关键词正则表达式"""
        for emotion, keywords in _EMOTION_KEYWORDS.items():
            patterns = []
            for keyword in keywords:
                # 创建不区分大小写的正则表达式
                pattern = re.compile(r'\b' + re.escape(keyword) + r'\b', re.IGNORECASE)
                patterns.append(pattern)
            self._compiled_patterns[emotion] = patterns
    
    def analyze(self, text: str, context: Optional[Dict] = None) -> Dict[str, Any]:
        """
        分析文本的情感
        
        Args:
            text: 要分析的文本
            context: 可选的上下文信息
            
        Returns:
            包含情感分析结果的字典
        """
        if not text or not text.strip():
            return {
                "primary_emotion": "neutral",
                "confidence": 0.0,
                "emotions": {},
                "tags": [],
                "score": 0.0,
            }
        
        if self._use_legacy:
            return self._analyze_legacy(text, context)
        
        # 计算各情感分数
        emotion_scores = self._calculate_emotion_scores(text)
        
        # 找到主要情感
        primary_emotion = max(emotion_scores.items(), key=lambda x: x[1])[0]
        confidence = emotion_scores[primary_emotion]
        
        # 生成情感标签
        tags = self.get_emotion_tags(emotion_scores)
        
        # 计算总体情感分数（正负平衡）
        score = self._calculate_overall_score(emotion_scores)
        
        return {
            "primary_emotion": primary_emotion,
            "confidence": confidence,
            "emotions": emotion_scores,
            "tags": tags,
            "score": score,
        }
    
    def _calculate_emotion_scores(self, text: str) -> Dict[str, float]:
        """计算各情感的分数"""
        scores = {emotion: 0.0 for emotion in _EMOTION_HIERARCHY}
        text_lower = text.lower()
        
        for emotion, patterns in self._compiled_patterns.items():
            match_count = 0
            for pattern in patterns:
                matches = pattern.findall(text_lower)
                match_count += len(matches)
            
            if match_count > 0:
                # 基础分数：匹配次数越多分数越高，但有上限
                base_score = min(match_count * 0.3, 1.0)
                # 根据情感层次调整分数范围
                layer = _EMOTION_HIERARCHY[emotion]["layer"]
                intensity_range = _EMOTION_HIERARCHY[emotion]["intensity_range"]
                
                # 层次越高的情感越难以触发
                layer_factor = 1.0 - (layer - 1) * 0.1
                adjusted_score = base_score * layer_factor
                
                # 限制在情感强度范围内
                scores[emotion] = max(intensity_range[0], min(adjusted_score, intensity_range[1]))
        
        return scores
    
    def _calculate_overall_score(self, emotion_scores: Dict[str, float]) -> float:
        """计算总体情感分数（-1到1，负数表示消极，正数表示积极）"""
        positive_score = 0.0
        negative_score = 0.0
        
        for emotion, score in emotion_scores.items():
            if score > 0:
                category = _EMOTION_HIERARCHY[emotion]["category"]
                if category == "positive":
                    positive_score += score
                elif category == "negative":
                    negative_score += score
                elif category == "mixed":
                    # 混合情感同时贡献正负分
                    positive_score += score * 0.5
                    negative_score += score * 0.5
        
        total_score = positive_score - negative_score
        # 归一化到 -1 到 1 范围
        return max(-1.0, min(total_score, 1.0))
    
    def _analyze_legacy(self, text: str, context: Optional[Dict] = None) -> Dict[str, Any]:
        """旧版简单关键词匹配算法"""
        text_lower = text.lower()
        emotion_counts = {emotion: 0 for emotion in _EMOTION_KEYWORDS}
        
        for emotion, keywords in _EMOTION_KEYWORDS.items():
            for keyword in keywords:
                if keyword.lower() in text_lower:
                    emotion_counts[emotion] += 1
        
        # 找到主要情感
        primary_emotion = max(emotion_counts.items(), key=lambda x: x[1])[0]
        if emotion_counts[primary_emotion] == 0:
            primary_emotion = "neutral"
            confidence = 0.0
        else:
            confidence = min(emotion_counts[primary_emotion] * 0.2, 1.0)
        
        # 计算情感分数
        emotion_scores = {emotion: min(count * 0.2, 1.0) for emotion, count in emotion_counts.items() if count > 0}
        
        # 生成标签
        tags = []
        for emotion, score in emotion_scores.items():
            if score > 0.3:
                tags.append(emotion)
        
        # 计算总体分数
        positive_emotions = ["joy", "trust", "anticipation", "love", "gratitude", "pride", "empathy"]
        negative_emotions = ["sadness", "anger", "fear", "disgust", "confusion", "frustration", "anxiety", "shame"]
        
        positive_score = sum(emotion_scores.get(e, 0) for e in positive_emotions)
        negative_score = sum(emotion_scores.get(e, 0) for e in negative_emotions)
        
        score = positive_score - negative_score
        score = max(-1.0, min(score, 1.0))
        
        return {
            "primary_emotion": primary_emotion,
            "confidence": confidence,
            "emotions": emotion_scores,
            "tags": tags,
            "score": score,
        }
    
    def batch_analyze(self, texts: List[str], contexts: Optional[List[Dict]] = None) -> List[Dict[str, Any]]:
        """
        批量分析多个文本的情感
        
        Args:
            texts: 文本列表
            contexts: 可选的上下文列表
            
        Returns:
            分析结果列表
        """
        if contexts is None:
            contexts = [None] * len(texts)
        
        results = []
        for text, context in zip(texts, contexts):
            result = self.analyze(text, context)
            results.append(result)
        
        return results
    
    def get_emotion_tags(self, emotion_scores: Dict[str, float], threshold: float = 0.3) -> List[str]:
        """
        获取情感标签
        
        Args:
            emotion_scores: 情感分数字典
            threshold: 标签阈值
            
        Returns:
            情感标签列表
        """
        tags = []
        for emotion, score in emotion_scores.items():
            if score >= threshold:
                tags.append(emotion)
        
        # 按分数降序排序
        tags.sort(key=lambda x: emotion_scores.get(x, 0), reverse=True)
        return tags
    
    def get_emotion_score(self, text: str, target_emotion: str) -> float:
        """
        获取文本对特定情感的分数
        
        Args:
            text: 文本
            target_emotion: 目标情感
            
        Returns:
            情感分数
        """
        if target_emotion not in _EMOTION_HIERARCHY:
            logger.warning(f"未知情感: {target_emotion}")
            return 0.0
        
        result = self.analyze(text)
        return result["emotions"].get(target_emotion, 0.0)
    
    def get_detailed_scores(self, text: str) -> Dict[str, Dict[str, Any]]:
        """
        获取详细的情感分数信息
        
        Args:
            text: 文本
            
        Returns:
            包含详细信息的情感分数字典
        """
        result = self.analyze(text)
        detailed = {}
        
        for emotion, score in result["emotions"].items():
            if score > 0:
                detailed[emotion] = {
                    "score": score,
                    "layer": _EMOTION_HIERARCHY[emotion]["layer"],
                    "category": _EMOTION_HIERARCHY[emotion]["category"],
                    "intensity_range": _EMOTION_HIERARCHY[emotion]["intensity_range"],
                }
        
        return detailed
    
    def get_emotion_hierarchy(self) -> Dict[str, Dict[str, Any]]:
        """
        获取情感层次结构
        
        Returns:
            情感层次结构字典
        """
        return _EMOTION_HIERARCHY.copy()
    
    def get_emotion_stats(self, texts: List[str]) -> Dict[str, Any]:
        """
        获取多个文本的情感统计信息
        
        Args:
            texts: 文本列表
            
        Returns:
            统计信息字典
        """
        results = self.batch_analyze(texts)
        
        # 统计主要情感分布
        primary_emotions: Dict[str, int] = {}
        for result in results:
            emotion = result["primary_emotion"]
            primary_emotions[emotion] = primary_emotions.get(emotion, 0) + 1
        
        # 计算平均情感分数
        scores = [result["score"] for result in results]
        avg_score = sum(scores) / len(scores) if scores else 0.0
        
        # 计算平均置信度
        confidences = [result["confidence"] for result in results]
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0
        
        return {
            "total_texts": len(texts),
            "primary_emotion_distribution": primary_emotions,
            "average_score": avg_score,
            "average_confidence": avg_confidence,
            "positive_ratio": sum(1 for s in scores if s > 0) / len(scores) if scores else 0.0,
            "negative_ratio": sum(1 for s in scores if s < 0) / len(scores) if scores else 0.0,
            "neutral_ratio": sum(1 for s in scores if s == 0) / len(scores) if scores else 0.0,
        }
    
    def get_emotion_distribution(self, texts: List[str]) -> Dict[str, float]:
        """
        获取多个文本的情感分布
        
        Args:
            texts: 文本列表
            
        Returns:
            情感分布字典
        """
        results = self.batch_analyze(texts)
        distribution: Dict[str, float] = {emotion: 0.0 for emotion in _EMOTION_HIERARCHY}
        
        for result in results:
            for emotion, score in result["emotions"].items():
                distribution[emotion] += score
        
        # 归一化
        total = sum(distribution.values())
        if total > 0:
            distribution = {emotion: score / total for emotion, score in distribution.items()}
        
        return distribution


# 全局单例
_emotion_analyzer: Optional[EmotionAnalyzer] = None
_analyzer_lock = threading.Lock()


def get_emotion_analyzer_instance() -> EmotionAnalyzer:
    """
    获取情感分析器单例实例
    
    使用单例模式避免重复初始化情感分析器，提升性能。
    """
    global _emotion_analyzer
    
    if _emotion_analyzer is None:
        with _analyzer_lock:
            if _emotion_analyzer is None:
                _emotion_analyzer = EmotionAnalyzer()
                logger.debug("创建新的 EmotionAnalyzer 单例")
    
    return _emotion_analyzer


def reset_emotion_analyzer() -> None:
    """
    重置情感分析器单例（主要用于测试）
    """
    global _emotion_analyzer
    
    with _analyzer_lock:
        _emotion_analyzer = None
        logger.debug("重置 EmotionAnalyzer 单例")