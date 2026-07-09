"""
温度引擎模块

实现记忆温度衰减和贝叶斯遗忘曲线。
支持：
- 基于时间的温度衰减
- 情感保护机制
- 饱和效应
- 贝叶斯遗忘概率
"""

from neurova.core.logger import get_logger
import math
import threading
from typing import Any, Dict

logger = get_logger(__name__)


def _validate_temp(value: float, name: str = "temperature") -> float:
    """校验温度/分数输入: 非 NaN、非负"""
    if not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be numeric, got {type(value).__name__}")
    if math.isnan(value) or math.isinf(value):
        raise ValueError(f"{name} must be finite, got {value}")
    return float(value)


def _validate_score(value: float, name: str = "score") -> float:
    """校验 0-1 范围的分数输入"""
    _validate_temp(value, name)
    return max(0.0, min(1.0, float(value)))


class _hybrid_method:
    """混合方法描述符: 实例调用使用实例参数, 类调用使用默认实例.

    BUG-3 修复: 原 on_access/on_decay 先定义为实例方法, 后用 @classmethod 覆盖,
    导致 engine.on_access() 实际调用 classmethod (使用默认实例, 忽略自定义参数).
    此描述符实现:
    - 类调用 TemperatureEngine.on_access(...) → 委托到 _get_default() (向后兼容)
    - 实例调用 engine.on_access(...) → 使用该实例的参数 (bug 修复)
    """

    def __init__(self, func):
        self._func = func
        self.__name__ = getattr(func, "__name__", "hybrid_method")

    def __set_name__(self, owner, name):
        self.__name__ = name

    def __get__(self, instance, owner=None):
        if instance is None:
            default = owner._get_default()

            def class_wrapper(*args, **kwargs):
                # 防御: 若此 wrapper 被当作类属性恢复(如测试 spy 还原后),
                # 实例访问会把它绑定为 bound method, 首参为实例.
                # 检测并使用该实例, 避免重复传入 default 导致参数冲突.
                if args and isinstance(args[0], owner):
                    actual = args[0]
                    return self._func(actual, *args[1:], **kwargs)
                return self._func(default, *args, **kwargs)
            return class_wrapper
        else:
            def instance_wrapper(*args, **kwargs):
                return self._func(instance, *args, **kwargs)
            return instance_wrapper


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

    # 类级别默认值（供 classmethod 兼容包装器使用）
    _CLASS_DECAY_RATE = 0.1
    _CLASS_EMOTIONAL_PROTECTION_THRESHOLD = 0.5
    _CLASS_EMOTIONAL_PROTECTION_FACTOR = 0.6

    # 默认实例（供类方法调用时使用，避免重复创建）
    _default_instance: "TemperatureEngine" = None
    # BUG-14 修复: _get_default() 单例创建需锁保护, 防止并发创建多实例
    _default_lock = threading.Lock()

    def __init__(
        self,
        base_decay_rate: float = 0.1,
        emotional_protection_threshold: float = 0.5,
        emotional_protection_factor: float = 0.6,
    ):
        """初始化温度引擎

        Args:
            base_decay_rate: 基础衰减率
            emotional_protection_threshold: 情感保护阈值
            emotional_protection_factor: 情感保护因子
        """
        self.base_decay_rate = base_decay_rate
        self.emotional_protection_threshold = emotional_protection_threshold
        self.emotional_protection_factor = emotional_protection_factor

        logger.debug("TemperatureEngine 初始化: decay_rate=%s", base_decay_rate)

    @_hybrid_method
    def on_access(
        self,
        current_temp: float,
        importance: float = 0.5,
        recall_count: int = 0,
        access_count: int = 0,
        emotion_score: float = 0.0,
        relation_count: int = 0,
    ) -> float:
        return self._on_access_impl(current_temp, importance, recall_count, access_count, emotion_score, relation_count)

    def _on_access_impl(
        self,
        current_temp: float,
        importance: float,
        recall_count: int,
        access_count: int,
        emotion_score: float,
        relation_count: int,
    ) -> float:
        """记忆被访问时更新温度

        Args:
            current_temp: 当前温度
            importance: 重要性分数 (0.0 - 1.0)
            recall_count: 回忆次数
            access_count: 访问次数(用于连击倍率)
            emotion_score: 情感分数 (0.0 - 1.0)
            relation_count: 关联记忆数

        Returns:
            float: 更新后的温度
        """
        # T-1: 输入校验
        current_temp = _validate_temp(current_temp, "current_temp")
        importance = _validate_score(importance, "importance")
        recall_count = max(0, int(recall_count))
        access_count = max(0, int(access_count))
        emotion_score = _validate_score(emotion_score, "emotion_score")
        relation_count = max(0, int(relation_count))

        # 访问升温 — 饱和效应: 高温时升温幅度减缓
        base_boost = 10.0 * importance * (self.base_decay_rate / 0.1)
        # 温度越高,升温空间越小 (90度时只有一半升温幅度)
        saturation = max(0.1, 1.0 - (current_temp / 100.0) * 0.8)
        access_boost = base_boost * saturation

        # 回忆次数加成
        recall_boost = min(recall_count * 2.0, 20.0)

        # 连击倍率: access_count%10 影响 multiplier (1.0 ~ 2.0)
        combo_multiplier = 1.0 + (access_count % 10) * 0.1

        # 情感加成
        emotion_bonus = emotion_score * 5.0

        # 关联加成 (上限 3.0)
        relation_bonus = min(relation_count * 0.5, 3.0)

        # 计算新温度
        new_temp = current_temp + (access_boost + recall_boost) * combo_multiplier + emotion_bonus + relation_bonus

        # 限制在有效范围内
        return max(0.0, min(100.0, new_temp))

    @_hybrid_method
    def on_decay(
        self,
        current_temp: float,
        last_accessed: str = None,
        days_idle: float = 0.0,
        importance: float = 0.5,
        emotion_score: float = 0.0,
        recall_count: int = 0,
        relation_count: int = 0,
        is_important: bool = False,
        is_crystallized: bool = False,
        combo_multiplier: float = 1.0,
    ) -> dict:
        return self._on_decay_impl(
            current_temp, last_accessed, days_idle, importance, emotion_score,
            recall_count, relation_count, is_important, is_crystallized, combo_multiplier,
        )

    def _on_decay_impl(
        self,
        current_temp: float,
        last_accessed: str,
        days_idle: float,
        importance: float,
        emotion_score: float,
        recall_count: int,
        relation_count: int,
        is_important: bool,
        is_crystallized: bool,
        combo_multiplier: float,
    ) -> dict:
        """计算温度衰减

        Args:
            current_temp: 当前温度
            last_accessed: 最后访问时间(ISO格式字符串)
            days_idle: 空闲天数(当 last_accessed 未提供时使用)
            importance: 重要性分数 (0.0 - 1.0)
            emotion_score: 情感分数 (0.0 - 1.0)
            recall_count: 回忆次数
            relation_count: 关联记忆数
            is_important: 是否重要记忆
            is_crystallized: 是否固化记忆
            combo_multiplier: 连击倍率

        Returns:
            dict: {'new_temp', 'lifecycle_stage', 'days_idle', 'decay_amount'}
        """
        # T-1: 输入校验
        current_temp = _validate_temp(current_temp, "current_temp")
        importance = _validate_score(importance, "importance")
        emotion_score = _validate_score(emotion_score, "emotion_score")
        recall_count = max(0, int(recall_count))
        relation_count = max(0, int(relation_count))

        # 计算空闲天数
        if last_accessed:
            try:
                from datetime import datetime as _dt
                if isinstance(last_accessed, str):
                    last_dt = _dt.fromisoformat(last_accessed)
                else:
                    last_dt = last_accessed
                days_idle = max(0.0, (_dt.now() - last_dt).total_seconds() / 86400.0)
            except (ValueError, TypeError):
                days_idle = max(0.0, days_idle)
        else:
            days_idle = max(0.0, _validate_temp(days_idle, "days_idle"))

        # 固化记忆不衰减
        if is_crystallized:
            return {
                'new_temp': current_temp,
                'lifecycle_stage': 'crystallized',
                'days_idle': days_idle,
                'decay_amount': 0.0,
            }

        # 高温记忆(>=80)不衰减(视为固化)
        if current_temp >= 80.0:
            return {
                'new_temp': current_temp,
                'lifecycle_stage': self._determine_stage(current_temp, days_idle, is_important),
                'days_idle': days_idle,
                'decay_amount': 0.0,
            }

        # 今天访问过的记忆不衰减
        if days_idle < 1.0:
            return {
                'new_temp': current_temp,
                'lifecycle_stage': self._determine_stage(current_temp, days_idle, is_important),
                'days_idle': days_idle,
                'decay_amount': 0.0,
            }

        # 1. 基础衰减率（贝叶斯遗忘曲线: 短期衰减快、长期衰减慢）
        curve_factor = self._calculate_curve_factor(days_idle)

        # 2. 情感保护（减缓衰减）— 使用实例配置
        emotion_protect = (
            self.emotional_protection_factor if emotion_score > self.emotional_protection_threshold else 1.0
        )

        # 3. 饱和效应（高温时衰减更快）
        saturation_factor = min(1.0, (current_temp / 100.0) ** 2)

        # 4. 重要性加权
        importance_weight = 1.0 - 0.5 * importance

        # 5. 关联保护（关联越多 → 保护越强 → 衰减因子越小）
        # 用除法: 关联越多,衰减率被压得越低
        relation_protection = 1.0 / (1.0 + relation_count * 0.1)

        # 6. 重要记忆保护
        important_protection = 0.5 if is_important else 1.0

        # 计算衰减率 (基础衰减率 * 各因子)
        decay_rate = min(
            0.95,
            curve_factor * emotion_protect * saturation_factor * importance_weight
            * relation_protection * important_protection
            * (self.base_decay_rate / 0.1),
        )

        # 应用衰减
        new_temp = current_temp * (1.0 - decay_rate)

        # 限制在有效范围内
        new_temp = max(0.0, min(100.0, new_temp))
        decay_amount = current_temp - new_temp

        # lifecycle_stage 基于原始温度(衰减前)判断
        return {
            'new_temp': new_temp,
            'lifecycle_stage': self._determine_stage(current_temp, days_idle, is_important),
            'days_idle': days_idle,
            'decay_amount': decay_amount,
        }

    @staticmethod
    def _determine_stage(temperature: float, days_idle: float = 0.0, is_important: bool = False) -> str:
        """根据温度确定生命周期阶段

        Args:
            temperature: 当前温度
            days_idle: 空闲天数
            is_important: 是否重要记忆(重要记忆最低 secondary)
        """
        if temperature >= 60.0:
            stage = 'active'
        elif temperature >= 40.0:
            stage = 'secondary'
        elif temperature >= 20.0:
            stage = 'secondary' if days_idle < 30 else 'archived'
        elif days_idle >= 60:
            stage = 'deleted'
        elif days_idle >= 30:
            stage = 'archived'
        else:
            stage = 'secondary' if temperature >= 10.0 else 'archived'

        # 重要记忆最低 secondary
        if is_important and stage == 'deleted':
            stage = 'secondary'
        if is_important and stage == 'archived':
            stage = 'secondary'

        return stage

    @staticmethod
    def should_upgrade_to_important(temperature: float, access_count: int = 0, emotion_score: float = 0.0, relation_count: int = 0) -> bool:
        """判断是否应升级为重要记忆"""
        if temperature >= 80.0:
            return True
        if access_count >= 10:
            return True
        if emotion_score >= 0.7:
            return True
        if relation_count >= 5:
            return True
        return False

    @staticmethod
    def should_crystallize(
        temperature: float,
        is_important: bool = False,
        emotion_score: float = 0.0,
        user_locked: bool = False,
        content: str = "",
        agent_marked_important: bool = False,
        metadata: dict = None,
    ) -> bool:
        """判断是否应固化"""
        meta = metadata or {}

        # 从 metadata 读取标志
        if meta.get("user_locked") or user_locked:
            return True
        if meta.get("agent_marked_important") or agent_marked_important:
            return True
        if is_important and temperature >= 80.0 and emotion_score >= 0.5:
            return True

        # 从 metadata.content 或 content 参数检查关键词
        check_content = meta.get("content", "") or content
        if check_content:
            special_keywords = ["生日", "密码", "地址", "电话", "纪念日"]
            if any(kw in check_content for kw in special_keywords):
                return True
            if "纪念日" in check_content or "anniversary" in check_content.lower():
                return True
        return False

    @classmethod
    def _calculate_curve_factor(cls, days_idle: float) -> float:
        """计算遗忘曲线因子

        基于空闲天数的分段函数（值越大衰减越快）：
        - ≤1天: 0.05 (极少衰减)
        - ≤7天: 0.1 (慢速衰减)
        - ≤30天: 0.2 (正常衰减)
        - >30天: 0.4 (快速衰减)

        Args:
            days_idle: 空闲天数

        Returns:
            float: 曲线因子 (0.0 - 1.0)
        """
        # Ebbinghaus 遗忘曲线: 短期衰减快、长期衰减慢
        # 1天=2.0, 7天=1.0, 30天=0.5, >30天=0.2
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
    def calculate_forgetting_probability(
        cls, temperature: float, days_idle: float, importance: float = 0.5, emotion_score: float = 0.0
    ) -> float:
        # T-1: 输入校验
        temperature = _validate_temp(temperature, "temperature")
        days_idle = max(0.0, _validate_temp(days_idle, "days_idle"))
        importance = _validate_score(importance, "importance")
        emotion_score = _validate_score(emotion_score, "emotion_score")
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
            },
        }

    # ── 默认实例管理 ──
    # on_access/on_decay 是实例方法（定义在类上方），不应被 classmethod 覆盖。
    # 旧代码如需以类方式调用，应显式使用 TemperatureEngine._get_default().on_access(...)

    @classmethod
    def _get_default(cls) -> "TemperatureEngine":
        """获取或创建默认实例（双重检查锁保护）

        BUG-14 修复: 原 _get_default() 无锁保护, 并发调用可能创建多个实例。
        现使用双重检查锁 (DCL) 模式: 第一次无锁检查避免热路径加锁,
        第二次持锁检查避免并发创建多实例。
        """
        if cls._default_instance is None:
            with cls._default_lock:
                if cls._default_instance is None:
                    cls._default_instance = cls()
        return cls._default_instance
