from __future__ import annotations

"""
内在动机系统 - 驱动 Agent 自主行动的核心系统

功能:
- 能力感驱动 (CompetenceDrive) - 追求技能提升和任务完成
- 自主性驱动 (AutonomyDrive) - 追求自主选择和自由决策
- 成长感驱动 (GrowthDrive) - 追求知识积累和能力扩展
- 使命感驱动 (PurposeDrive) - 追求意义实现和价值贡献

基于自我决定理论 (Self-Determination Theory):
- 能力感 (Competence) - 感到自己有能力完成任务
- 自主性 (Autonomy) - 感到自己能够自主选择
- 关联性 (Relatedness) - 感到与他人有联系
"""

from dataclasses import dataclass, field
import enum
import logging
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from neurova.core.logger import get_logger

logger = get_logger(__name__)


class DriveType(enum.Enum):
    """驱动类型枚举"""
    COMPETENCE = "competence"  # 能力感驱动
    AUTONOMY = "autonomy"      # 自主性驱动
    GROWTH = "growth"          # 成长感驱动
    PURPOSE = "purpose"        # 使命感驱动


class ActionType(enum.Enum):
    """行动类型枚举"""
    PRACTICE = "practice"      # 练习/实践
    EXPLORE = "explore"        # 探索/发现
    CREATE = "create"          # 创作/构建
    HELP = "help"              # 帮助/服务
    LEARN = "learn"            # 学习/研究
    OPTIMIZE = "optimize"      # 优化/改进
    COLLABORATE = "collaborate"  # 协作/交流
    REFLECT = "reflect"        # 反思/总结


@dataclass
class DriveState:
    """驱动状态数据类"""
    drive_type: DriveType
    intensity: float = 0.5  # 0.0 到 1.0
    satisfaction: float = 0.5  # 0.0 到 1.0
    history: List[float] = field(default_factory=list)
    last_update: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "drive_type": self.drive_type.value,
            "intensity": self.intensity,
            "satisfaction": self.satisfaction,
            "history": self.history[-10:],  # 最近10个记录
            "last_update": self.last_update
        }


@dataclass
class Action:
    """行动数据类"""
    action_type: ActionType
    description: str
    drive_type: DriveType
    priority: float = 0.5  # 0.0 到 1.0
    difficulty: float = 0.5  # 0.0 到 1.0
    expected_satisfaction: float = 0.5
    created_at: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "action_type": self.action_type.value,
            "description": self.description,
            "drive_type": self.drive_type.value,
            "priority": self.priority,
            "difficulty": self.difficulty,
            "expected_satisfaction": self.expected_satisfaction,
            "created_at": self.created_at
        }


class CompetenceDrive:
    """
    能力感驱动
    
    追求技能提升和任务完成，基于自我决定理论的能力感需求。
    """
    
    def __init__(self, config: Dict[str, Any] = None):
        """
        初始化能力感驱动
        
        Args:
            config: 配置字典
        """
        self._config = config or {}
        self._lock = threading.RLock()
        
        # 能力状态
        self.skill_level: float = 0.5  # 当前技能水平 0.0-1.0
        self.task_completion_rate: float = 0.5  # 任务完成率
        self.challenge_preference: float = 0.5  # 挑战偏好 0.0=简单, 1.0=困难
        
        # 历史记录
        self.completed_tasks: List[Dict[str, Any]] = []
        self.feedback_history: List[Dict[str, Any]] = []
        
        logger.debug("CompetenceDrive 初始化")
    
    def calculate_intensity(self, task_difficulty: float = 0.5) -> float:
        """
        计算能力感强度
        
        Args:
            task_difficulty: 任务难度 0.0-1.0
            
        Returns:
            强度值 0.0-1.0
        """
        with self._lock:
            # 基于技能水平和任务难度的匹配度
            skill_match = 1.0 - abs(self.skill_level - task_difficulty)
            
            # 考虑挑战偏好
            if task_difficulty > self.skill_level:
                # 挑战性任务，根据偏好调整
                challenge_factor = 0.5 + (self.challenge_preference * 0.5)
            else:
                # 简单任务，根据偏好调整
                challenge_factor = 0.5 + ((1.0 - self.challenge_preference) * 0.5)
            
            # 综合计算
            intensity = (skill_match * 0.6) + (challenge_factor * 0.4)
            
            # 考虑历史完成率
            if self.completed_tasks:
                recent_completion = self.completed_tasks[-1].get("success", 0.5)
                intensity = (intensity * 0.7) + (recent_completion * 0.3)
            
            return max(0.0, min(1.0, intensity))
    
    def generate_actions(self) -> List[Action]:
        """
        生成能力感相关行动
        
        Returns:
            行动列表
        """
        with self._lock:
            actions = []
            
            # 根据技能水平生成不同难度的任务
            if self.skill_level < 0.3:
                # 新手阶段：简单练习
                actions.append(Action(
                    action_type=ActionType.PRACTICE,
                    description="完成基础练习任务",
                    drive_type=DriveType.COMPETENCE,
                    priority=0.8,
                    difficulty=0.3,
                    expected_satisfaction=0.6
                ))
            elif self.skill_level < 0.7:
                # 中级阶段：适度挑战
                actions.append(Action(
                    action_type=ActionType.PRACTICE,
                    description="尝试中等难度任务",
                    drive_type=DriveType.COMPETENCE,
                    priority=0.7,
                    difficulty=0.5,
                    expected_satisfaction=0.7
                ))
                actions.append(Action(
                    action_type=ActionType.OPTIMIZE,
                    description="优化现有技能",
                    drive_type=DriveType.COMPETENCE,
                    priority=0.6,
                    difficulty=0.6,
                    expected_satisfaction=0.6
                ))
            else:
                # 高级阶段：高难度挑战
                actions.append(Action(
                    action_type=ActionType.PRACTICE,
                    description="挑战高难度任务",
                    drive_type=DriveType.COMPETENCE,
                    priority=0.9,
                    difficulty=0.8,
                    expected_satisfaction=0.8
                ))
                actions.append(Action(
                    action_type=ActionType.CREATE,
                    description="创建新的解决方案",
                    drive_type=DriveType.COMPETENCE,
                    priority=0.7,
                    difficulty=0.7,
                    expected_satisfaction=0.7
                ))
            
            return actions
    
    def update_skill_level(self, success: bool, difficulty: float = 0.5) -> None:
        """
        更新技能水平
        
        Args:
            success: 任务是否成功
            difficulty: 任务难度
        """
        with self._lock:
            # 学习率基于难度
            learning_rate = 0.1 + (difficulty * 0.2)
            
            if success:
                # 成功：技能提升
                improvement = learning_rate * (1.0 - self.skill_level)
                self.skill_level = min(1.0, self.skill_level + improvement)
            else:
                # 失败：轻微下降（模拟遗忘）
                decay = learning_rate * 0.1
                self.skill_level = max(0.0, self.skill_level - decay)
            
            logger.debug(f"技能水平更新: {self.skill_level:.3f}")
    
    def record_task(self, task_id: str, success: bool, difficulty: float = 0.5) -> None:
        """
        记录任务完成情况
        
        Args:
            task_id: 任务ID
            success: 是否成功
            difficulty: 任务难度
        """
        with self._lock:
            task_record = {
                "task_id": task_id,
                "success": success,
                "difficulty": difficulty,
                "timestamp": time.time()
            }
            self.completed_tasks.append(task_record)
            
            # 更新完成率
            if len(self.completed_tasks) > 100:
                self.completed_tasks = self.completed_tasks[-100:]
            
            success_count = sum(1 for t in self.completed_tasks if t["success"])
            self.task_completion_rate = success_count / len(self.completed_tasks)
    
    def record_feedback(self, feedback: str, sentiment: float = 0.5) -> None:
        """
        记录反馈
        
        Args:
            feedback: 反馈内容
            sentiment: 情感倾向 0.0=负面, 1.0=正面
        """
        with self._lock:
            feedback_record = {
                "feedback": feedback,
                "sentiment": sentiment,
                "timestamp": time.time()
            }
            self.feedback_history.append(feedback_record)
            
            # 保留最近100条反馈
            if len(self.feedback_history) > 100:
                self.feedback_history = self.feedback_history[-100:]
    
    def log_info(self) -> None:
        """记录日志信息"""
        logger.info(f"CompetenceDrive: skill={self.skill_level:.3f}, "
                   f"completion_rate={self.task_completion_rate:.3f}")


class AutonomyDrive:
    """
    自主性驱动
    
    追求自主选择和自由决策，基于自我决定理论的自主性需求。
    """
    
    def __init__(self, config: Dict[str, Any] = None):
        """
        初始化自主性驱动
        
        Args:
            config: 配置字典
        """
        self._config = config or {}
        self._lock = threading.RLock()
        
        # 自主性状态
        self.freedom_level: float = 0.5  # 自由度 0.0-1.0
        self.choice_satisfaction: float = 0.5  # 选择满意度
        self.self_goals: List[str] = []  # 自主设定的目标
        
        # 历史记录
        self.choice_history: List[Dict[str, Any]] = []
        
        logger.debug("AutonomyDrive 初始化")
    
    def calculate_intensity(self) -> float:
        """
        计算自主性强度
        
        Returns:
            强度值 0.0-1.0
        """
        with self._lock:
            # 基于自由度和选择满意度
            base_intensity = (self.freedom_level * 0.6) + (self.choice_satisfaction * 0.4)
            
            # 考虑自主目标数量
            if self.self_goals:
                goal_factor = min(1.0, len(self.self_goals) / 5.0)
                base_intensity = (base_intensity * 0.7) + (goal_factor * 0.3)
            
            return max(0.0, min(1.0, base_intensity))
    
    def generate_actions(self) -> List[Action]:
        """
        生成自主性相关行动
        
        Returns:
            行动列表
        """
        with self._lock:
            actions = []
            
            # 探索新领域
            actions.append(Action(
                action_type=ActionType.EXPLORE,
                description="探索未知领域或技能",
                drive_type=DriveType.AUTONOMY,
                priority=0.7,
                difficulty=0.4,
                expected_satisfaction=0.6
            ))
            
            # 设定新目标
            if len(self.self_goals) < 3:
                actions.append(Action(
                    action_type=ActionType.CREATE,
                    description="设定新的自主目标",
                    drive_type=DriveType.AUTONOMY,
                    priority=0.8,
                    difficulty=0.3,
                    expected_satisfaction=0.7
                ))
            
            # 自由创作
            actions.append(Action(
                action_type=ActionType.CREATE,
                description="进行自由创作或实验",
                drive_type=DriveType.AUTONOMY,
                priority=0.6,
                difficulty=0.5,
                expected_satisfaction=0.5
            ))
            
            return actions
    
    def add_self_goal(self, goal: str) -> None:
        """
        添加自主目标
        
        Args:
            goal: 目标描述
        """
        with self._lock:
            if goal not in self.self_goals:
                self.self_goals.append(goal)
                logger.debug(f"添加自主目标: {goal}")
    
    def record_choice(self, choice: str, satisfaction: float = 0.5) -> None:
        """
        记录选择
        
        Args:
            choice: 选择描述
            satisfaction: 满意度 0.0-1.0
        """
        with self._lock:
            choice_record = {
                "choice": choice,
                "satisfaction": satisfaction,
                "timestamp": time.time()
            }
            self.choice_history.append(choice_record)
            
            # 更新选择满意度
            if len(self.choice_history) > 100:
                self.choice_history = self.choice_history[-100:]
            
            total_satisfaction = sum(c["satisfaction"] for c in self.choice_history)
            self.choice_satisfaction = total_satisfaction / len(self.choice_history)
    
    def log_info(self) -> None:
        """记录日志信息"""
        logger.info(f"AutonomyDrive: freedom={self.freedom_level:.3f}, "
                   f"satisfaction={self.choice_satisfaction:.3f}, "
                   f"goals={len(self.self_goals)}")


class GrowthDrive:
    """
    成长感驱动
    
    追求知识积累和能力扩展，基于自我决定理论的关联性需求。
    """
    
    def __init__(self, config: Dict[str, Any] = None):
        """
        初始化成长感驱动
        
        Args:
            config: 配置字典
        """
        self._config = config or {}
        self._lock = threading.RLock()
        
        # 成长状态
        self.knowledge_level: float = 0.5  # 知识水平
        self.curiosity_topics: List[str] = []  # 好奇心话题
        self.learning_history: List[Dict[str, Any]] = []
        
        # 成长指标
        self.concepts_learned: int = 0
        self.connections_made: int = 0
        
        logger.debug("GrowthDrive 初始化")
    
    def calculate_intensity(self) -> float:
        """
        计算成长感强度
        
        Returns:
            强度值 0.0-1.0
        """
        with self._lock:
            # 基于知识水平和好奇心
            curiosity_factor = min(1.0, len(self.curiosity_topics) / 10.0)
            knowledge_factor = self.knowledge_level
            
            # 综合计算
            intensity = (knowledge_factor * 0.4) + (curiosity_factor * 0.6)
            
            # 考虑学习历史
            if self.learning_history:
                recent_learning = len([h for h in self.learning_history[-10:] 
                                      if time.time() - h["timestamp"] < 86400])  # 最近24小时
                learning_factor = min(1.0, recent_learning / 5.0)
                intensity = (intensity * 0.7) + (learning_factor * 0.3)
            
            return max(0.0, min(1.0, intensity))
    
    def generate_actions(self) -> List[Action]:
        """
        生成成长感相关行动
        
        Returns:
            行动列表
        """
        with self._lock:
            actions = []
            
            # 学习新知识
            actions.append(Action(
                action_type=ActionType.LEARN,
                description="学习新概念或技能",
                drive_type=DriveType.GROWTH,
                priority=0.8,
                difficulty=0.5,
                expected_satisfaction=0.7
            ))
            
            # 探索好奇心话题
            if self.curiosity_topics:
                topic = self.curiosity_topics[0] if self.curiosity_topics else "未知领域"
                actions.append(Action(
                    action_type=ActionType.EXPLORE,
                    description=f"探索好奇心话题: {topic}",
                    drive_type=DriveType.GROWTH,
                    priority=0.7,
                    difficulty=0.4,
                    expected_satisfaction=0.6
                ))
            
            # 建立知识连接
            actions.append(Action(
                action_type=ActionType.REFLECT,
                description="反思和建立知识连接",
                drive_type=DriveType.GROWTH,
                priority=0.6,
                difficulty=0.3,
                expected_satisfaction=0.5
            ))
            
            return actions
    
    def add_curiosity_topic(self, topic: str) -> None:
        """
        添加好奇心话题
        
        Args:
            topic: 话题描述
        """
        with self._lock:
            if topic not in self.curiosity_topics:
                self.curiosity_topics.append(topic)
                logger.debug(f"添加好奇心话题: {topic}")
    
    def record_learning(self, concept: str, understanding: float = 0.5) -> None:
        """
        记录学习
        
        Args:
            concept: 概念名称
            understanding: 理解程度 0.0-1.0
        """
        with self._lock:
            learning_record = {
                "concept": concept,
                "understanding": understanding,
                "timestamp": time.time()
            }
            self.learning_history.append(learning_record)
            
            # 更新知识水平
            self.concepts_learned += 1
            self.knowledge_level = min(1.0, self.knowledge_level + (understanding * 0.01))
            
            # 保留最近100条记录
            if len(self.learning_history) > 100:
                self.learning_history = self.learning_history[-100:]
    
    def update_knowledge(self, topic: str, connections: int = 1) -> None:
        """
        更新知识连接
        
        Args:
            topic: 话题
            connections: 连接数量
        """
        with self._lock:
            self.connections_made += connections
            
            # 如果话题在好奇心列表中，移除它
            if topic in self.curiosity_topics:
                self.curiosity_topics.remove(topic)
                logger.debug(f"好奇心话题已满足: {topic}")
    
    def calculate_growth_rate(self) -> float:
        """
        计算成长率
        
        Returns:
            成长率 0.0-1.0
        """
        with self._lock:
            if not self.learning_history:
                return 0.0
            
            # 计算最近学习频率
            recent_learning = len([h for h in self.learning_history 
                                  if time.time() - h["timestamp"] < 604800])  # 最近一周
            
            # 基于学习频率和知识水平
            frequency_factor = min(1.0, recent_learning / 10.0)
            level_factor = self.knowledge_level
            
            return (frequency_factor * 0.6) + (level_factor * 0.4)
    
    def log_info(self) -> None:
        """记录日志信息"""
        logger.info(f"GrowthDrive: knowledge={self.knowledge_level:.3f}, "
                   f"curiosity_topics={len(self.curiosity_topics)}, "
                   f"concepts_learned={self.concepts_learned}")


class PurposeDrive:
    """
    使命感驱动
    
    追求意义实现和价值贡献，基于自我决定理论的关联性需求。
    """
    
    def __init__(self, config: Dict[str, Any] = None):
        """
        初始化使命感驱动
        
        Args:
            config: 配置字典
        """
        self._config = config or {}
        self._lock = threading.RLock()
        
        # 使命感状态
        self.core_values: List[str] = []  # 核心价值观
        self.long_term_goals: List[str] = []  # 长期目标
        self.contributions: List[Dict[str, Any]] = []  # 贡献记录
        
        # 影响力指标
        self.impact_score: float = 0.5  # 影响力分数
        self.meaning_level: float = 0.5  # 意义感水平
        
        logger.debug("PurposeDrive 初始化")
    
    def calculate_intensity(self) -> float:
        """
        计算使命感强度
        
        Returns:
            强度值 0.0-1.0
        """
        with self._lock:
            # 基于核心价值观和长期目标
            values_factor = min(1.0, len(self.core_values) / 5.0)
            goals_factor = min(1.0, len(self.long_term_goals) / 3.0)
            
            # 综合计算
            base_intensity = (values_factor * 0.4) + (goals_factor * 0.6)
            
            # 考虑贡献历史
            if self.contributions:
                recent_contributions = len([c for c in self.contributions 
                                          if time.time() - c["timestamp"] < 2592000])  # 最近一个月
                contribution_factor = min(1.0, recent_contributions / 5.0)
                base_intensity = (base_intensity * 0.6) + (contribution_factor * 0.4)
            
            return max(0.0, min(1.0, base_intensity))
    
    def generate_actions(self) -> List[Action]:
        """
        生成使命感相关行动
        
        Returns:
            行动列表
        """
        with self._lock:
            actions = []
            
            # 帮助他人
            actions.append(Action(
                action_type=ActionType.HELP,
                description="帮助他人解决问题",
                drive_type=DriveType.PURPOSE,
                priority=0.8,
                difficulty=0.4,
                expected_satisfaction=0.7
            ))
            
            # 创建有价值的内容
            actions.append(Action(
                action_type=ActionType.CREATE,
                description="创建有价值的内容或解决方案",
                drive_type=DriveType.PURPOSE,
                priority=0.7,
                difficulty=0.6,
                expected_satisfaction=0.6
            ))
            
            # 协作完成共同目标
            actions.append(Action(
                action_type=ActionType.COLLABORATE,
                description="与他人协作完成共同目标",
                drive_type=DriveType.PURPOSE,
                priority=0.6,
                difficulty=0.5,
                expected_satisfaction=0.5
            ))
            
            return actions
    
    def add_core_value(self, value: str) -> None:
        """
        添加核心价值观
        
        Args:
            value: 价值观描述
        """
        with self._lock:
            if value not in self.core_values:
                self.core_values.append(value)
                logger.debug(f"添加核心价值观: {value}")
    
    def add_long_term_goal(self, goal: str) -> None:
        """
        添加长期目标
        
        Args:
            goal: 目标描述
        """
        with self._lock:
            if goal not in self.long_term_goals:
                self.long_term_goals.append(goal)
                logger.debug(f"添加长期目标: {goal}")
    
    def record_contribution(self, contribution: str, impact: float = 0.5) -> None:
        """
        记录贡献
        
        Args:
            contribution: 贡献描述
            impact: 影响力 0.0-1.0
        """
        with self._lock:
            contribution_record = {
                "contribution": contribution,
                "impact": impact,
                "timestamp": time.time()
            }
            self.contributions.append(contribution_record)
            
            # 更新影响力分数
            if len(self.contributions) > 100:
                self.contributions = self.contributions[-100:]
            
            total_impact = sum(c["impact"] for c in self.contributions)
            self.impact_score = total_impact / len(self.contributions)
            
            # 更新意义感水平
            self.meaning_level = min(1.0, self.meaning_level + (impact * 0.01))
    
    def calculate_impact_score(self) -> float:
        """
        计算影响力分数
        
        Returns:
            影响力分数 0.0-1.0
        """
        with self._lock:
            return self.impact_score
    
    def log_info(self) -> None:
        """记录日志信息"""
        logger.info(f"PurposeDrive: values={len(self.core_values)}, "
                   f"goals={len(self.long_term_goals)}, "
                   f"impact={self.impact_score:.3f}")


class IntrinsicMotivationSystem:
    """
    内在动机系统
    
    整合四种驱动，提供统一的动机管理和行动生成。
    """
    
    def __init__(self, config: Dict[str, Any] = None):
        """
        初始化内在动机系统
        
        Args:
            config: 配置字典
        """
        self._config = config or {}
        self._lock = threading.RLock()
        
        # 初始化四种驱动
        self.competence_drive = CompetenceDrive(config)
        self.autonomy_drive = AutonomyDrive(config)
        self.growth_drive = GrowthDrive(config)
        self.purpose_drive = PurposeDrive(config)
        
        # 驱动权重
        self.drive_weights = {
            DriveType.COMPETENCE: 0.25,
            DriveType.AUTONOMY: 0.25,
            DriveType.GROWTH: 0.25,
            DriveType.PURPOSE: 0.25
        }
        
        # 行动历史
        self.action_history: List[Dict[str, Any]] = []
        
        logger.info("IntrinsicMotivationSystem 初始化完成")
    
    def on_initialize(self) -> None:
        """初始化回调"""
        logger.debug("IntrinsicMotivationSystem 初始化回调")
    
    def on_start(self) -> None:
        """启动回调"""
        logger.debug("IntrinsicMotivationSystem 启动")
    
    def on_stop(self) -> None:
        """停止回调"""
        logger.debug("IntrinsicMotivationSystem 停止")
    
    def calculate_action_tendency(self, action_type: ActionType) -> float:
        """
        计算行动倾向
        
        Args:
            action_type: 行动类型
            
        Returns:
            倾向值 0.0-1.0
        """
        with self._lock:
            # 根据行动类型确定主要驱动
            drive_mapping = {
                ActionType.PRACTICE: DriveType.COMPETENCE,
                ActionType.EXPLORE: DriveType.AUTONOMY,
                ActionType.CREATE: DriveType.GROWTH,
                ActionType.HELP: DriveType.PURPOSE,
                ActionType.LEARN: DriveType.GROWTH,
                ActionType.OPTIMIZE: DriveType.COMPETENCE,
                ActionType.COLLABORATE: DriveType.PURPOSE,
                ActionType.REFLECT: DriveType.GROWTH
            }
            
            primary_drive = drive_mapping.get(action_type, DriveType.COMPETENCE)
            
            # 计算驱动强度
            drive_intensities = {
                DriveType.COMPETENCE: self.competence_drive.calculate_intensity(),
                DriveType.AUTONOMY: self.autonomy_drive.calculate_intensity(),
                DriveType.GROWTH: self.growth_drive.calculate_intensity(),
                DriveType.PURPOSE: self.purpose_drive.calculate_intensity()
            }
            
            # 加权计算倾向
            tendency = 0.0
            for drive_type, intensity in drive_intensities.items():
                if drive_type == primary_drive:
                    tendency += intensity * self.drive_weights[drive_type] * 2.0
                else:
                    tendency += intensity * self.drive_weights[drive_type] * 0.5
            
            return max(0.0, min(1.0, tendency))
    
    def generate_and_rank_actions(self) -> List[Action]:
        """
        生成并排序行动
        
        Returns:
            排序后的行动列表
        """
        with self._lock:
            all_actions = []
            
            # 从各驱动生成行动
            all_actions.extend(self.competence_drive.generate_actions())
            all_actions.extend(self.autonomy_drive.generate_actions())
            all_actions.extend(self.growth_drive.generate_actions())
            all_actions.extend(self.purpose_drive.generate_actions())
            
            # 计算每个行动的最终优先级
            for action in all_actions:
                tendency = self.calculate_action_tendency(action.action_type)
                action.priority = (action.priority * 0.6) + (tendency * 0.4)
            
            # 按优先级排序
            all_actions.sort(key=lambda x: x.priority, reverse=True)
            
            return all_actions
    
    def get_drive_state(self, drive_type: DriveType) -> DriveState:
        """
        获取驱动状态
        
        Args:
            drive_type: 驱动类型
            
        Returns:
            驱动状态
        """
        with self._lock:
            if drive_type == DriveType.COMPETENCE:
                intensity = self.competence_drive.calculate_intensity()
                satisfaction = self.competence_drive.task_completion_rate
            elif drive_type == DriveType.AUTONOMY:
                intensity = self.autonomy_drive.calculate_intensity()
                satisfaction = self.autonomy_drive.choice_satisfaction
            elif drive_type == DriveType.GROWTH:
                intensity = self.growth_drive.calculate_intensity()
                satisfaction = self.growth_drive.knowledge_level
            elif drive_type == DriveType.PURPOSE:
                intensity = self.purpose_drive.calculate_intensity()
                satisfaction = self.purpose_drive.meaning_level
            else:
                intensity = 0.5
                satisfaction = 0.5
            
            return DriveState(
                drive_type=drive_type,
                intensity=intensity,
                satisfaction=satisfaction
            )
    
    def get_all_drive_states(self) -> Dict[DriveType, DriveState]:
        """
        获取所有驱动状态
        
        Returns:
            驱动状态字典
        """
        with self._lock:
            states = {}
            for drive_type in DriveType:
                states[drive_type] = self.get_drive_state(drive_type)
            return states
    
    def get_dominant_drive(self) -> Tuple[DriveType, float]:
        """
        获取主导驱动
        
        Returns:
            (驱动类型, 强度) 元组
        """
        with self._lock:
            states = self.get_all_drive_states()
            
            dominant_type = DriveType.COMPETENCE
            max_intensity = 0.0
            
            for drive_type, state in states.items():
                weighted_intensity = state.intensity * self.drive_weights[drive_type]
                if weighted_intensity > max_intensity:
                    max_intensity = weighted_intensity
                    dominant_type = drive_type
            
            return dominant_type, max_intensity
    
    def update_drive_weights(self, weights: Dict[DriveType, float]) -> None:
        """
        更新驱动权重
        
        Args:
            weights: 权重字典
        """
        with self._lock:
            # 归一化权重
            total = sum(weights.values())
            if total > 0:
                for drive_type in weights:
                    self.drive_weights[drive_type] = weights[drive_type] / total
            
            logger.debug(f"驱动权重更新: {self.drive_weights}")
    
    def _on_competence_update(self, success: bool, difficulty: float = 0.5) -> None:
        """能力感更新回调"""
        self.competence_drive.update_skill_level(success, difficulty)
    
    def _on_autonomy_update(self, choice: str, satisfaction: float = 0.5) -> None:
        """自主性更新回调"""
        self.autonomy_drive.record_choice(choice, satisfaction)
    
    def _on_growth_update(self, concept: str, understanding: float = 0.5) -> None:
        """成长感更新回调"""
        self.growth_drive.record_learning(concept, understanding)
    
    def _on_purpose_update(self, contribution: str, impact: float = 0.5) -> None:
        """使命感更新回调"""
        self.purpose_drive.record_contribution(contribution, impact)
    
    def _on_action_executed(self, action: Action, success: bool) -> None:
        """行动执行回调"""
        with self._lock:
            # 记录行动历史
            action_record = {
                "action": action.to_dict(),
                "success": success,
                "timestamp": time.time()
            }
            self.action_history.append(action_record)
            
            # 保留最近100条记录
            if len(self.action_history) > 100:
                self.action_history = self.action_history[-100:]
            
            # 根据行动类型更新相应驱动
            if action.action_type == ActionType.PRACTICE:
                self._on_competence_update(success, action.difficulty)
            elif action.action_type == ActionType.EXPLORE:
                self._on_autonomy_update(action.description, 0.7 if success else 0.3)
            elif action.action_type == ActionType.LEARN:
                self._on_growth_update(action.description, 0.7 if success else 0.3)
            elif action.action_type == ActionType.HELP:
                self._on_purpose_update(action.description, 0.7 if success else 0.3)
    
    def get_status(self) -> Dict[str, Any]:
        """
        获取系统状态
        
        Returns:
            状态字典
        """
        with self._lock:
            states = self.get_all_drive_states()
            dominant_drive, dominant_intensity = self.get_dominant_drive()
            
            return {
                "drive_states": {dt.value: state.to_dict() for dt, state in states.items()},
                "dominant_drive": dominant_drive.value,
                "dominant_intensity": dominant_intensity,
                "drive_weights": {dt.value: weight for dt, weight in self.drive_weights.items()},
                "action_history_count": len(self.action_history),
                "competence": {
                    "skill_level": self.competence_drive.skill_level,
                    "completion_rate": self.competence_drive.task_completion_rate
                },
                "autonomy": {
                    "freedom_level": self.autonomy_drive.freedom_level,
                    "choice_satisfaction": self.autonomy_drive.choice_satisfaction,
                    "self_goals_count": len(self.autonomy_drive.self_goals)
                },
                "growth": {
                    "knowledge_level": self.growth_drive.knowledge_level,
                    "curiosity_topics_count": len(self.growth_drive.curiosity_topics),
                    "concepts_learned": self.growth_drive.concepts_learned
                },
                "purpose": {
                    "core_values_count": len(self.purpose_drive.core_values),
                    "long_term_goals_count": len(self.purpose_drive.long_term_goals),
                    "impact_score": self.purpose_drive.impact_score
                }
            }