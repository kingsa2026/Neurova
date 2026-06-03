"""
温度引擎模块

实现记忆温度衰减和贝叶斯遗忘曲线。
支持：
- 基于时间的温度衰减
- 情感保护机制
- 饱和效应
- 贝叶斯遗忘概率
"""

import math
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class TemperatureEngine:
    """温度引擎
    
    管理记忆的"温度"（活跃度），实现贝叶斯遗忘曲线。
    
    温度值范围：0.0（完全遗忘）到 100.0（高度活跃）
    
    核心公式：
    - 衰减因子 = f(空闲天数)
    - 情感保护 = 情感分数 > 0.5 ? 0.6 : 1.0
    - 饱和效应 = 1.0 - (当前温度 / 100.0)^2
    - 最终衰减 = 衰减因子 × 情感保护 × 饱和效应
    """
    
    # 生命周期阶段
    STAGE_ACTIVE = "active"
    STAGE_SECONDARY = "secondary" 
    STAGE_ARCHIVED = "archived"
    STAGE_DELETED = "deleted"
    
    # 生命周期阈值
    THRESHOLD_SECONDARY = 60.0
    THRESHOLD_ARCHIVED = 20.0
    THRESHOLD_DELETED = 5.0
    
    # 类级别默认值（供 classmethod 使用）
    _CLASS_DECAY_RATE = 0.1
    _CLASS_EMOTIONAL_PROTECTION_THRESHOLD = 0.5
    _CLASS_EMOTIONAL_PROTECTION_FACTOR = 0.6
    
    def __init__(self, 
                 base_decay_rate: float = 0.1,
                 emotional_protection_threshold: float = 0.5,
                 emotional_protection_factor: float = 0.6):
        """初始化温度引擎
        
        Args:
            base_decay_rate: 基础衰减率
            emotional_protection_threshold: 情感保护阈值
            emotional_protection_factor: 情感保护因子
        """
        self.base_decay_rate = base_decay_rate
        self.emotional_protection_threshold = emotional_protection_threshold
        self.emotional_protection_factor = emotional_protection_factor
        
        logger.debug(f"TemperatureEngine 初始化: decay_rate={base_decay_rate}")
    
    @classmethod
    def on_access(cls, current_temp: float, 
                  importance: float = 0.5,
                  recall_count: int = 0) -> float:
        """记忆被访问时更新温度
        
        Args:
            current_temp: 当前温度
            importance: 重要性分数 (0.0 - 1.0)
            recall_count: 回忆次数
            
        Returns:
            float: 更新后的温度
        """
        # 访问升温
        access_boost = 10.0 * importance
        
        # 回忆次数加成
        recall_boost = min(recall_count * 2.0, 20.0)
        
        # 计算新温度
        new_temp = current_temp + access_boost + recall_boost
        
        # 限制在有效范围内
        return max(0.0, min(100.0, new_temp))
    
    @classmethod
    def on_decay(cls, current_temp: float,
                 days_idle: float,
                 importance: float = 0.5,
                 emotion_score: float = 0.0,
                 recall_count: int = 0) -> float:
        """计算温度衰减
        
        Args:
            current_temp: 当前温度
            days_idle: 空闲天数
            importance: 重要性分数 (0.0 - 1.0)
            emotion_score: 情感分数 (0.0 - 1.0)
            recall_count: 回忆次数
            
        Returns:
            float: 衰减后的温度
        """
        # 1. 计算衰减因子（贝叶斯遗忘曲线）
        curve_factor = cls._calculate_curve_factor(days_idle)
        
        # 2. 情感保护
        emotion_protect = (cls._CLASS_EMOTIONAL_PROTECTION_FACTOR 
                          if emotion_score > cls._CLASS_EMOTIONAL_PROTECTION_THRESHOLD 
                          else 1.0)
        
        # 3. 饱和效应
        saturation_factor = 1.0 - (current_temp / 100.0) ** 2
        
        # 4. 重要性加权（重要记忆衰减更少）
        importance_weight = 1.0 - 0.5 * importance
        
        # 5. 回忆次数保护
        recall_protection = min(1.0 + recall_count * 0.05, 1.5)
        
        # 6. 计算最终衰减
        decay = curve_factor * emotion_protect * saturation_factor * importance_weight
        
        # 应用衰减
        new_temp = current_temp * (1.0 - decay)
        
        # 最后应用回忆保护（防止过度衰减）
        new_temp = max(new_temp, current_temp * recall_protection * 0.1)
        
        return max(0.0, min(100.0, new_temp))
    
    @classmethod
    def _calculate_curve_factor(cls, days_idle: float) -> float:
        """计算遗忘曲线因子
        
        基于空闲天数的分段函数：
        - ≤1天: 2.0 (快速衰减)
        - ≤7天: 1.0 (正常衰减)
        - ≤30天: 0.5 (慢速衰减)
        - >30天: 0.2 (极慢衰减)
        
        Args:
            days_idle: 空闲天数
            
        Returns:
            float: 曲线因子
        """
        if days_idle <= 1:
            return 2.0
        elif days_idle <= 7:
            return 1.0
        elif days_idle <= 30:
            return 0.5
        else:
            return 0.2
    
    @classmethod
    def get_lifecycle_stage(cls, temperature: float) -> str:
        """根据温度获取生命周期阶段
        
        Args:
            temperature: 温度值
            
        Returns:
            str: 生命周期阶段
        """
        if temperature >= cls.THRESHOLD_SECONDARY:
            return cls.STAGE_ACTIVE
        elif temperature >= cls.THRESHOLD_ARCHIVED:
            return cls.STAGE_SECONDARY
        elif temperature >= cls.THRESHOLD_DELETED:
            return cls.STAGE_ARCHIVED
        else:
            return cls.STAGE_DELETED
    
    @classmethod
    def calculate_forgetting_probability(cls, 
                                         temperature: float,
                                         days_idle: float,
                                         importance: float = 0.5,
                                         emotion_score: float = 0.0) -> float:
        """计算贝叶斯遗忘概率
        
        P(forget|evidence) = 1 - P(retain|evidence)
        
        P(retain|evidence) ∝ P(evidence|retain) * P(retain)
        
        Args:
            temperature: 当前温度
            days_idle: 空闲天数
            importance: 重要性分数
            emotion_score: 情感分数
            
        Returns:
            float: 遗忘概率 (0.0 - 1.0)
        """
        # 先验概率 P(retain) = temperature / 100
        prior_retain = temperature / 100.0
        
        # 似然 P(evidence|retain) 基于空闲天数
        if days_idle <= 1:
            likelihood = 0.9  # 最近访问过，不太可能遗忘
        elif days_idle <= 7:
            likelihood = 0.7
        elif days_idle <= 30:
            likelihood = 0.4
        else:
            likelihood = 0.1
        
        # 重要性和情感的调整因子
        adjustment = (0.5 + 0.5 * importance) * (0.8 + 0.2 * emotion_score)
        
        # 后验概率
        posterior_retain = likelihood * prior_retain * adjustment
        
        # 归一化（简化版）
        forgetting_prob = 1.0 - min(1.0, posterior_retain)
        
        return max(0.0, min(1.0, forgetting_prob))
    
    def get_stats(self) -> Dict[str, Any]:
        """获取引擎统计信息
        
        Returns:
            Dict[str, Any]: 统计信息
        """
        return {
            "base_decay_rate": self.base_decay_rate,
            "emotional_protection_threshold": self.emotional_protection_threshold,
            "emotional_protection_factor": self.emotional_protection_factor,
            "lifecycle_thresholds": {
                "secondary": self.THRESHOLD_SECONDARY,
                "archived": self.THRESHOLD_ARCHIVED,
                "deleted": self.THRESHOLD_DELETED,
            }
        }