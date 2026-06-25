"""
EKI认知优化框架 - Ensemble Kalman Inversion for Cognitive Optimization

已实现组件:
1. 集合卡尔曼反演（简化版） - 无梯度贝叶斯推断
2. 信息增益量化（简化版） - 任务价值评估
3. EKICognitiveOptimizer: 认知优化器
4. TaskValue: 任务价值级别
5. ReinforcementAction: 强化动作

未实现组件（诚实标注）:
- 嵌入式代表性采样 — 未实现
- 代理模型（高斯过程） — 未实现

设计理念:
- 用EKI近似贝叶斯后验
- 集合粒子表示参数分布
- 通过观测更新参数

注意: 当前实现为简化版，非真正 EKI 算法。高斯过程代理模型和嵌入式采样未实现。
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
