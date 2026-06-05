"""
自动分类器 - Auto Classifier for Memory

功能:
1. 自动推断记忆分类 (category)
2. 自动推断记忆类型 (type)
3. 自动推断记忆视角 (perspective)
4. 自动判断重要性 (is_important)
5. 自动判断是否固化 (is_crystallized)

基于关键词规则和上下文分析进行智能分类
"""

import re
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
import logging

from .models import Memory, MemoryType, MemoryCategory, MemoryPerspective, EmotionType

logger = logging.getLogger(__name__)


# ────── Enums ──────

class CategoryType(Enum):
    """记忆分类类型"""
    GENERAL = "general"           # 通用
    CONVERSATION = "conversation" # 对话
    KNOWLEDGE = "knowledge"       # 知识
    EXPERIENCE = "experience"     # 经验
    TOOL_USAGE = "tool_usage"     # 工具使用
    REFLECTION = "reflection"     # 反思
    USER_PREFERENCE = "user_preference"  # 用户偏好


class MemoryTypeEnum(Enum):
    """记忆类型枚举"""
    SEMANTIC = "semantic"         # 语义记忆（事实知识）
    EPISODIC = "episodic"         # 情景记忆（事件经历）
    PROCEDURAL = "procedural"     # 程序记忆（技能操作）
    PATTERN = "pattern"           # 模式记忆（行为模式）
    EMOTIONAL = "emotional"       # 情感记忆
    WORKING = "working"           # 工作记忆


class PerspectiveType(Enum):
    """记忆视角类型"""
    FIRST_PERSON = "first_person"    # 第一人称
    SECOND_PERSON = "second_person"  # 第二人称
    THIRD_PERSON = "third_person"    # 第三人称
    SYSTEM = "system"                # 系统视角


# ────── Keywords Rules ──────

# 分类关键词规则
_CATEGORY_KEYWORDS = {
    CategoryType.CONVERSATION: [
        r"说|讲|问|答|聊|讨论|对话|交流|沟通",
        r"said|asked|answered|discussed|talked|chatted",
        r"用户说|我问|他回答|我们讨论",
    ],
    CategoryType.KNOWLEDGE: [
        r"定义|概念|原理|理论|公式|定理|知识|学习|理解",
        r"definition|concept|principle|theory|formula|theorem|knowledge|learn|understand",
        r"这是因为|原因是|根据|研究表明|资料显示",
    ],
    CategoryType.EXPERIENCE: [
        r"经历|经验|教训|体会|感悟|心得|实践|尝试",
        r"experience|lesson|insight|practice|try|attempt",
        r"我曾经|我试过|我发现|我学到|这次经历",
    ],
    CategoryType.TOOL_USAGE: [
        r"工具|命令|函数|API|代码|程序|脚本|操作",
        r"tool|command|function|API|code|program|script|operation",
        r"使用工具|调用函数|执行命令|运行代码",
    ],
    CategoryType.REFLECTION: [
        r"反思|思考|总结|分析|评估|回顾|复盘|改进",
        r"reflect|think|summarize|analyze|evaluate|review|improve",
        r"我反思|我总结|我分析|我评估|我回顾",
    ],
    CategoryType.USER_PREFERENCE: [
        r"喜欢|讨厌|偏好|习惯|风格|设置|配置|选择",
        r"like|hate|prefer|habit|style|setting|config|choice",
        r"我喜欢|我讨厌|我偏好|我习惯|我的风格",
    ],
}

# 类型关键词规则
_TYPE_KEYWORDS = {
    MemoryType.SEMANTIC: [
        r"定义|概念|事实|知识|信息|数据|属性|特征",
        r"definition|concept|fact|knowledge|information|data|attribute|feature",
        r"是什么|属于|包含|具有|意味着",
    ],
    MemoryType.EPISODIC: [
        r"事件|经历|发生|时间|地点|人物|经过|结果",
        r"event|happen|occur|time|place|person|process|result",
        r"在.*时候|当.*时|有一次|那次|昨天|今天",
    ],
    MemoryType.PROCEDURAL: [
        r"步骤|流程|方法|操作|技能|技巧|教程|指南",
        r"step|process|method|operation|skill|technique|tutorial|guide",
        r"第一步|首先|然后|最后|如何|怎么",
    ],
    MemoryType.PATTERN: [
        r"模式|规律|习惯|趋势|重复|循环|常态|惯例",
        r"pattern|rule|habit|trend|repeat|cycle|normal|routine",
        r"总是|经常|通常|往往|每次|反复",
    ],
    MemoryType.EMOTIONAL: [
        r"情感|情绪|感觉|心情|感受|感动|激动|平静",
        r"emotion|feeling|mood|touch|excite|calm",
        r"感到|觉得|心情|情绪|感动|开心|难过",
    ],
    MemoryType.WORKING: [
        r"当前|现在|正在|临时|暂存|待办|任务|工作",
        r"current|now|working|temporary|todo|task|job",
        r"正在做|现在要|当前任务|待办事项",
    ],
}

# 视角关键词规则
_PERSPECTIVE_KEYWORDS = {
    PerspectiveType.FIRST_PERSON: [
        r"我|我们|自己|本人|咱|咱们",
        r"I|we|myself|ourselves",
    ],
    PerspectiveType.SECOND_PERSON: [
        r"你|您|你们|你方|贵方",
        r"you|your|yours",
    ],
    PerspectiveType.THIRD_PERSON: [
        r"他|她|它|他们|她们|它们|某人|某物",
        r"he|she|it|they|them|someone|something",
    ],
    PerspectiveType.SYSTEM: [
        r"系统|程序|AI|智能体|助手|机器人",
        r"system|program|AI|agent|assistant|robot",
    ],
}

# 重要性关键词
_IMPORTANT_KEYWORDS = [
    r"重要|关键|核心|必须|必要|紧急|优先|严重",
    r"important|key|core|must|necessary|urgent|priority|critical",
    r"记住|注意|小心|警告|提醒|强调",
    r"remember|note|careful|warning|remind|emphasize",
]

# 固化关键词
_CRYSTALLIZE_KEYWORDS = [
    r"永远|永久|长期|不变|固定|稳定|经典|基础",
    r"forever|permanent|long.term|unchanged|fixed|stable|classic|basic",
    r"原则|规律|定律|真理|常识|标准",
    r"principle|rule|law|truth|common.sense|standard",
]


class MemoryAutoClassifier:
    """
    记忆自动分类器
    
    基于关键词规则和上下文分析进行智能分类。
    """
    
    def __init__(self):
        """初始化分类器"""
        self._compiled_patterns: Dict[str, List[re.Pattern]] = {}
        self._compile_patterns()
        logger.info("MemoryAutoClassifier 初始化完成")
    
    def _compile_patterns(self):
        """预编译所有关键词模式"""
        all_keywords = {
            **{f"category_{k.value}": v for k, v in _CATEGORY_KEYWORDS.items()},
            **{f"type_{k.value}": v for k, v in _TYPE_KEYWORDS.items()},
            **{f"perspective_{k.value}": v for k, v in _PERSPECTIVE_KEYWORDS.items()},
            "important": _IMPORTANT_KEYWORDS,
            "crystallize": _CRYSTALLIZE_KEYWORDS,
        }
        
        for key, patterns in all_keywords.items():
            compiled = []
            for pattern in patterns:
                try:
                    compiled.append(re.compile(pattern, re.IGNORECASE))
                except re.error:
                    logger.warning(f"无法编译正则表达式: {pattern}")
            self._compiled_patterns[key] = compiled
    
    def classify(self, content: str, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        分类记忆内容
        
        Args:
            content: 记忆内容
            metadata: 可选的元数据
            
        Returns:
            分类结果字典
        """
        if not content or not content.strip():
            return self._default_classification()
        
        # 分类各个维度
        category, category_confidence = self.classify_category(content)
        memory_type, type_confidence = self.classify_type(content)
        perspective, perspective_confidence = self.classify_perspective(content)
        emotion = self.classify_emotion(content)
        important = self.is_important(content)
        crystallize = self.should_crystallize(content)
        
        # 计算总体置信度
        overall_confidence = self._calculate_overall_confidence(
            category_confidence, type_confidence, perspective_confidence
        )
        
        # 生成推理过程
        reasoning = self._generate_reasoning(
            content, category, memory_type, perspective, important, crystallize
        )
        
        # 使用情感亲和性增强分类
        if metadata and "emotion" in metadata:
            category = self._enhance_with_emotion_affinity(category, metadata["emotion"])
        
        return {
            "category": category,
            "memory_type": memory_type,
            "perspective": perspective,
            "emotion": emotion,
            "is_important": important,
            "is_crystallized": crystallize,
            "confidence": overall_confidence,
            "reasoning": reasoning,
            "details": {
                "category_confidence": category_confidence,
                "type_confidence": type_confidence,
                "perspective_confidence": perspective_confidence,
            },
        }
    
    def _enhance_with_emotion_affinity(self, category: CategoryType, emotion: str) -> CategoryType:
        """使用情感亲和性增强分类"""
        # 情感与分类的亲和性映射
        emotion_affinity = {
            "joy": {CategoryType.EXPERIENCE: 0.3, CategoryType.REFLECTION: 0.2},
            "sadness": {CategoryType.EXPERIENCE: 0.3, CategoryType.REFLECTION: 0.3},
            "anger": {CategoryType.EXPERIENCE: 0.4, CategoryType.REFLECTION: 0.2},
            "fear": {CategoryType.EXPERIENCE: 0.3, CategoryType.REFLECTION: 0.3},
            "surprise": {CategoryType.EXPERIENCE: 0.4, CategoryType.KNOWLEDGE: 0.2},
            "trust": {CategoryType.KNOWLEDGE: 0.3, CategoryType.USER_PREFERENCE: 0.3},
            "anticipation": {CategoryType.EXPERIENCE: 0.3, CategoryType.REFLECTION: 0.2},
            "confusion": {CategoryType.KNOWLEDGE: 0.4, CategoryType.REFLECTION: 0.3},
            "frustration": {CategoryType.EXPERIENCE: 0.4, CategoryType.REFLECTION: 0.3},
            "love": {CategoryType.USER_PREFERENCE: 0.4, CategoryType.EXPERIENCE: 0.3},
            "gratitude": {CategoryType.EXPERIENCE: 0.4, CategoryType.REFLECTION: 0.3},
            "nostalgia": {CategoryType.EXPERIENCE: 0.5, CategoryType.REFLECTION: 0.3},
            "anxiety": {CategoryType.EXPERIENCE: 0.3, CategoryType.REFLECTION: 0.4},
            "pride": {CategoryType.EXPERIENCE: 0.4, CategoryType.REFLECTION: 0.3},
            "shame": {CategoryType.EXPERIENCE: 0.4, CategoryType.REFLECTION: 0.4},
            "empathy": {CategoryType.CONVERSATION: 0.4, CategoryType.EXPERIENCE: 0.3},
        }
        
        if emotion in emotion_affinity:
            affinity = emotion_affinity[emotion]
            # 如果当前分类有情感亲和性加成，保持不变
            if category in affinity:
                return category
            
            # 否则，考虑是否有更高亲和性的分类
            best_affinity_category = max(affinity.items(), key=lambda x: x[1])
            if best_affinity_category[1] > 0.4:  # 阈值
                return best_affinity_category[0]
        
        return category
    
    def classify_category(self, content: str) -> Tuple[CategoryType, float]:
        """
        分类记忆分类
        
        Args:
            content: 记忆内容
            
        Returns:
            (分类类型, 置信度)
        """
        scores: Dict[CategoryType, float] = {cat: 0.0 for cat in CategoryType}
        
        for category, patterns in _CATEGORY_KEYWORDS.items():
            key = f"category_{category.value}"
            if key in self._compiled_patterns:
                for pattern in self._compiled_patterns[key]:
                    matches = pattern.findall(content)
                    if matches:
                        # 每个匹配增加分数，但有上限
                        scores[category] += min(len(matches) * 0.2, 0.8)
        
        # 找到最高分
        if not any(scores.values()):
            return CategoryType.GENERAL, 0.5
        
        best_category = max(scores.items(), key=lambda x: x[1])
        
        # 归一化置信度
        total = sum(scores.values())
        confidence = best_category[1] / total if total > 0 else 0.5
        
        return best_category[0], confidence
    
    def classify_category_multi_label(self, content: str, threshold: float = 0.3) -> List[Tuple[CategoryType, float]]:
        """
        多标签分类
        
        Args:
            content: 记忆内容
            threshold: 阈值
            
        Returns:
            超过阈值的分类列表
        """
        scores: Dict[CategoryType, float] = {cat: 0.0 for cat in CategoryType}
        
        for category, patterns in _CATEGORY_KEYWORDS.items():
            key = f"category_{category.value}"
            if key in self._compiled_patterns:
                for pattern in self._compiled_patterns[key]:
                    matches = pattern.findall(content)
                    if matches:
                        scores[category] += min(len(matches) * 0.2, 0.8)
        
        # 归一化
        total = sum(scores.values())
        if total > 0:
            scores = {k: v / total for k, v in scores.items()}
        
        # 过滤超过阈值的
        results = [(cat, score) for cat, score in scores.items() if score >= threshold]
        results.sort(key=lambda x: x[1], reverse=True)
        
        return results
    
    def classify_type(self, content: str) -> Tuple[MemoryTypeEnum, float]:
        """
        分类记忆类型
        
        Args:
            content: 记忆内容
            
        Returns:
            (记忆类型, 置信度)
        """
        scores: Dict[MemoryTypeEnum, float] = {t: 0.0 for t in MemoryTypeEnum}
        
        for memory_type, patterns in _TYPE_KEYWORDS.items():
            key = f"type_{memory_type.value}"
            if key in self._compiled_patterns:
                for pattern in self._compiled_patterns[key]:
                    matches = pattern.findall(content)
                    if matches:
                        scores[memory_type] += min(len(matches) * 0.2, 0.8)
        
        # 找到最高分
        if not any(scores.values()):
            return MemoryTypeEnum.SEMANTIC, 0.5
        
        best_type = max(scores.items(), key=lambda x: x[1])
        
        # 归一化置信度
        total = sum(scores.values())
        confidence = best_type[1] / total if total > 0 else 0.5
        
        return best_type[0], confidence
    
    def classify_perspective(self, content: str) -> Tuple[PerspectiveType, float]:
        """
        分类记忆视角
        
        Args:
            content: 记忆内容
            
        Returns:
            (视角类型, 置信度)
        """
        scores: Dict[PerspectiveType, float] = {p: 0.0 for p in PerspectiveType}
        
        for perspective, patterns in _PERSPECTIVE_KEYWORDS.items():
            key = f"perspective_{perspective.value}"
            if key in self._compiled_patterns:
                for pattern in self._compiled_patterns[key]:
                    matches = pattern.findall(content)
                    if matches:
                        scores[perspective] += min(len(matches) * 0.3, 0.9)
        
        # 找到最高分
        if not any(scores.values()):
            return PerspectiveType.FIRST_PERSON, 0.5
        
        best_perspective = max(scores.items(), key=lambda x: x[1])
        
        # 归一化置信度
        total = sum(scores.values())
        confidence = best_perspective[1] / total if total > 0 else 0.5
        
        return best_perspective[0], confidence
    
    def classify_emotion(self, content: str) -> EmotionType:
        """
        分类情感类型
        
        Args:
            content: 记忆内容
            
        Returns:
            情感类型
        """
        # 简单关键词匹配
        emotion_keywords = {
            EmotionType.JOY: ["开心", "快乐", "高兴", "喜悦", "兴奋", "happy", "joy", "excited"],
            EmotionType.SADNESS: ["悲伤", "难过", "伤心", "沮丧", "sad", "unhappy", "depressed"],
            EmotionType.ANGER: ["愤怒", "生气", "恼怒", "angry", "furious", "mad"],
            EmotionType.FEAR: ["恐惧", "害怕", "担心", "焦虑", "afraid", "fear", "anxious"],
            EmotionType.SURPRISE: ["惊讶", "震惊", "吃惊", "surprised", "shocked"],
            EmotionType.DISGUST: ["厌恶", "恶心", "反感", "disgusted", "repulsed"],
            EmotionType.TRUST: ["信任", "相信", "信赖", "trust", "believe"],
            EmotionType.ANTICIPATION: ["期待", "盼望", "期望", "anticipate", "expect"],
        }
        
        content_lower = content.lower()
        scores: Dict[EmotionType, float] = {e: 0.0 for e in EmotionType}
        
        for emotion, keywords in emotion_keywords.items():
            for keyword in keywords:
                if keyword.lower() in content_lower:
                    scores[emotion] += 1.0
        
        if not any(scores.values()):
            return EmotionType.NEUTRAL
        
        return max(scores.items(), key=lambda x: x[1])[0]
    
    def is_important(self, content: str) -> bool:
        """
        判断记忆是否重要
        
        Args:
            content: 记忆内容
            
        Returns:
            是否重要
        """
        if "important" in self._compiled_patterns:
            for pattern in self._compiled_patterns["important"]:
                if pattern.search(content):
                    return True
        return False
    
    def should_crystallize(self, content: str) -> bool:
        """
        判断记忆是否应该固化
        
        Args:
            content: 记忆内容
            
        Returns:
            是否应该固化
        """
        if "crystallize" in self._compiled_patterns:
            for pattern in self._compiled_patterns["crystallize"]:
                if pattern.search(content):
                    return True
        return False
    
    def _default_classification(self) -> Dict[str, Any]:
        """默认分类结果"""
        return {
            "category": CategoryType.GENERAL,
            "memory_type": MemoryTypeEnum.SEMANTIC,
            "perspective": PerspectiveType.FIRST_PERSON,
            "emotion": EmotionType.NEUTRAL,
            "is_important": False,
            "is_crystallized": False,
            "confidence": 0.5,
            "reasoning": "内容为空，使用默认分类",
            "details": {
                "category_confidence": 0.5,
                "type_confidence": 0.5,
                "perspective_confidence": 0.5,
            },
        }
    
    def _calculate_overall_confidence(
        self,
        category_confidence: float,
        type_confidence: float,
        perspective_confidence: float,
    ) -> float:
        """计算总体置信度"""
        # 加权平均
        weights = [0.4, 0.4, 0.2]  # 分类和类型权重更高
        confidences = [category_confidence, type_confidence, perspective_confidence]
        
        weighted_sum = sum(w * c for w, c in zip(weights, confidences))
        return weighted_sum
    
    def _generate_reasoning(
        self,
        content: str,
        category: CategoryType,
        memory_type: MemoryTypeEnum,
        perspective: PerspectiveType,
        is_important: bool,
        should_crystallize: bool,
    ) -> str:
        """生成推理过程"""
        reasoning_parts = []
        
        # 分类推理
        reasoning_parts.append(f"分类为 {category.value}：")
        key = f"category_{category.value}"
        if key in self._compiled_patterns:
            for pattern in self._compiled_patterns[key]:
                matches = pattern.findall(content)
                if matches:
                    reasoning_parts.append(f"  - 匹配关键词: {matches[:3]}")
        
        # 类型推理
        reasoning_parts.append(f"类型为 {memory_type.value}：")
        key = f"type_{memory_type.value}"
        if key in self._compiled_patterns:
            for pattern in self._compiled_patterns[key]:
                matches = pattern.findall(content)
                if matches:
                    reasoning_parts.append(f"  - 匹配关键词: {matches[:3]}")
        
        # 重要性推理
        if is_important:
            reasoning_parts.append("标记为重要：匹配重要性关键词")
        
        # 固化推理
        if should_crystallize:
            reasoning_parts.append("建议固化：匹配固化关键词")
        
        return "\n".join(reasoning_parts)