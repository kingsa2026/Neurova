"""
EKI认知优化框架 - Ensemble Kalman Inversion for Cognitive Optimization

功能:
1. 集合卡尔曼反演 - 无梯度贝叶斯推断
2. 信息增益量化 - 任务价值评估
3. 嵌入式代表性采样 - 高效参数采样
4. 代理模型 - 高斯过程加速计算

设计理念:
- 用EKI近似贝叶斯后验
- 集合粒子表示参数分布
- 通过观测更新参数

核心组件:
- EKICognitiveOptimizer: 认知优化器
- TaskValue: 任务价值级别
- ReinforcementAction: 强化动作
"""

from .cognitive_optimizer import (
    EKICognitiveOptimizer,
    MemoryState,
    ReinforcementAction,
    TaskResult,
    TaskValue,
    get_cognitive_optimizer,
    reset_cognitive_optimizer,
)

__all__ = [
    "EKICognitiveOptimizer",
    "TaskValue",
    "TaskResult",
    "MemoryState",
    "ReinforcementAction",
    "get_cognitive_optimizer",
    "reset_cognitive_optimizer",
]
