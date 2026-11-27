"""
EKI认知优化框架 - Ensemble Kalman Inversion for Cognitive Optimization

已实现组件:
1. ekiUpdate —— 一步随机集合卡尔曼反演更新（扰动观测 + 协方差膨胀）；
   EKIModule 的记忆状态更新复用本函数（单一事实源）
2. GaussianProcessSurrogate —— 高斯过程代理模型（RBF/Matérn 核、
   边缘似然调参、后验预测/采样）
3. EKICognitiveOptimizer —— 认知优化器（train_surrogate 已接真
   高斯过程代理，surrogatePredict 提供读面）
4. TaskValue / ReinforcementAction / TaskResult / MemoryState

仍未实现 / 简化（诚实标注）:
- EKICognitiveOptimizer._compute_information_gain 仍为词汇启发式，非真正信息增益
- EKICognitiveOptimizer._flush_updates 未实现（显式抛 NotImplementedError）
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
from .gp_surrogate import GaussianProcessSurrogate
from .inversion import ekiUpdate

__all__ = [
    "ekiUpdate",
    "GaussianProcessSurrogate",
    "EKICognitiveOptimizer",
    "TaskValue",
    "TaskResult",
    "MemoryState",
    "ReinforcementAction",
    "get_cognitive_optimizer",
    "reset_cognitive_optimizer",
]
