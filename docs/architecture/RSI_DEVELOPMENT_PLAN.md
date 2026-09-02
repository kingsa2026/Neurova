# RSI 开发计划

**版本**: v1.1  
**日期**: 2026-06-08  
**状态**: 闭环完成  
**方法论**: 测试驱动开发（TDD）

---

## 1. 开发概述

### 1.1 目标

基于 RSI 架构设计文档 v1.3，实现递归自我改进（RSI）系统的核心模块。

### 1.2 开发方法

采用测试驱动开发（TDD）方法：
- **RED**: 编写失败的测试
- **GREEN**: 编写最小代码让测试通过
- **REFACTOR**: 重构代码

### 1.3 开发顺序

按以下顺序开发（从核心到外围）：

1. **Phase 1**: RSIIntegrationManager（集成管理器）
2. **Phase 2**: ConvergenceAnalyzer（收敛性分析器）
3. **Phase 3**: RSIMetrics（监控指标）
4. **Phase 4**: RSIRollbackManager（回滚管理器）
5. **Phase 5**: RSIDeploymentController（部署控制器）
6. **Phase 6**: RSIDashboard（仪表盘）

---

## 2. Phase 1: RSIIntegrationManager

### 2.1 核心思想

RSI 不是独立系统，而是建立在现有四大闭环系统之上的元优化层。

### 2.2 公共接口

```python
class RSIIntegrationManager:
    """RSI 集成管理器 - 协调 RSI 与四大闭环的交互"""
    
    def __init__(self, 
                 sleep_system: Any,
                 emotion_system: Any,
                 experience_system: Any,
                 tool_memory_system: Any):
        """
        初始化 RSI 集成管理器
        
        Args:
            sleep_system: 睡眠闭环系统
            emotion_system: 情感闭环系统
            experience_system: 经验闭环系统
            tool_memory_system: 工具记忆闭环系统
        """
    
    def get_optimizable_parameters(self) -> Dict[str, List[ParameterInfo]]:
        """
        获取四大闭环系统中可被 RSI 优化的参数
        
        Returns:
            Dict[str, List[ParameterInfo]]: 
            {
                'sleep': [ParameterInfo(...), ...],
                'emotion': [ParameterInfo(...), ...],
                'experience': [ParameterInfo(...), ...],
                'tool_memory': [ParameterInfo(...), ...]
            }
        """
    
    def collect_feedback_signals(self) -> Dict[str, Any]:
        """
        从四大闭环系统收集反馈信号
        
        Returns:
            Dict[str, Any]: 
            {
                'sleep': {...},
                'emotion': {...},
                'experience': {...},
                'tool_memory': {...}
            }
        """
    
    def apply_optimization(self, parameter_path: str, new_value: Any) -> bool:
        """
        应用优化到指定参数
        
        Args:
            parameter_path: 参数路径，格式为 "system.parameter_name"
                例如: "sleep.base_decay_rate", "emotion.decay_rate"
            new_value: 新的参数值
            
        Returns:
            bool: 是否成功应用
        """
    
    def get_system_status(self) -> Dict[str, Any]:
        """
        获取四大闭环系统的状态
        
        Returns:
            Dict[str, Any]: 各系统的运行状态
        """
```

### 2.3 可优化参数映射

| 闭环系统 | 参数名 | 当前值 | 描述 |
|----------|--------|--------|------|
| **睡眠闭环** | `base_decay_rate` | 0.1 | 基础衰减率 |
| | `similarity_threshold` | 0.8 | 相似度阈值 |
| | `merge_threshold` | 3 | 合并阈值 |
| **情感闭环** | `emotional_protection_threshold` | 0.5 | 情感保护阈值 |
| | `emotional_protection_factor` | 0.6 | 情感保护因子 |
| **经验闭环** | `crystallize_min_observations` | 3 | 最小观察次数 |
| | `crystallize_min_success_rate` | 0.6 | 最小成功率 |
| | `pattern_min_support` | 0.1 | 模式最小支持度 |
| **工具记忆闭环** | `success_bonus` | 0.1 | 成功奖励 |
| | `failure_penalty` | 0.9 | 失败惩罚 |
| | `decay_rate` | 0.01 | 衰减率 |
| | `muscle_memory_threshold` | 0.7 | 肌肉记忆阈值 |

### 2.4 测试计划

**测试文件**: `tests/unit/test_rsi_integration_manager.py`

**测试用例**:

1. **test_initialization**
   - 验证能正确初始化并连接四大闭环系统
   - 验证系统状态为"active"

2. **test_get_optimizable_parameters**
   - 验证能发现四大闭环系统中的可优化参数
   - 验证参数数量正确
   - 验证参数类型正确

3. **test_collect_feedback_signals**
   - 验证能从四大闭环系统收集反馈信号
   - 验证信号格式正确

4. **test_apply_optimization**
   - 验证能安全地应用优化到指定参数
   - 验证参数值已更新
   - 验证无效参数路径返回 False

5. **test_get_system_status**
   - 验证能获取四大闭环系统的当前状态
   - 验证状态信息完整

---

## 3. Phase 2: ConvergenceAnalyzer

### 3.1 核心思想

为 RSI 提供严格的数学证明，确保递归过程不会发散。

### 3.2 公共接口

```python
class ConvergenceAnalyzer:
    """收敛性分析器 - 数学保证 RSI 收敛"""
    
    def __init__(self, 
                 window_size: int = 20,
                 convergence_threshold: float = 0.01,
                 divergence_threshold: float = -0.05):
        """
        初始化收敛性分析器
        
        Args:
            window_size: 滑动窗口大小
            convergence_threshold: 收敛阈值（增益小于此值认为收敛）
            divergence_threshold: 发散阈值（增益小于此值认为发散）
        """
    
    def record_iteration(self, gain: float, cost: float) -> None:
        """
        记录一轮 RSI 迭代的增益和成本
        
        Args:
            gain: 改进增益
            cost: 计算成本
        """
    
    def analyze_convergence(self) -> Dict[str, Any]:
        """
        分析收敛状态
        
        Returns:
            Dict[str, Any]:
            {
                'status': 'converging' | 'converged' | 'diverging' | 'oscillating' | 'insufficient_data',
                'confidence': float,  # 置信度 [0, 1]
                'recommendation': str,  # 建议
                'metrics': {
                    'mean_gain': float,
                    'std_dev': float,
                    'trend_slope': float,
                }
            }
        """
    
    def compute_roi(self) -> float:
        """
        计算投资回报率
        
        Returns:
            float: ROI = 总增益 / 总成本
        """
    
    def predict_convergence_point(self) -> Optional[int]:
        """
        预测收敛点
        
        Returns:
            Optional[int]: 预测的收敛迭代次数，如果无法预测返回 None
        """
    
    def is_worth_continuing(self) -> bool:
        """
        判断是否值得继续进化
        
        Returns:
            bool: 如果 ROI > 0 且未发散，返回 True
        """
```

### 3.3 收敛性定理

**定理 1: 棘轮收敛性**

若 RSI 满足以下条件：
1. **棘轮单调性**: $P(S_{t+1}) \geq P(S_t), \forall t$
2. **性能有界性**: $P(S) \leq P_{max}, \forall S$
3. **增益递减性**: $\lim_{t \to \infty} E[G_t] = 0$

则 RSI 必然收敛: $\exists T^*$ 使得 $\forall t > T^*, G_t = 0$

### 3.4 测试计划

**测试文件**: `tests/unit/test_convergence_analyzer.py`

**测试用例**:

1. **test_initialization**
   - 验证能正确初始化
   - 验证默认参数正确

2. **test_record_iteration**
   - 验证能正确记录增益和成本
   - 验证历史记录长度正确
   - 验证窗口大小限制

3. **test_analyze_convergence_insufficient_data**
   - 验证数据不足时返回 "insufficient_data"

4. **test_analyze_convergence_converging**
   - 验证能检测到收敛趋势
   - 验证置信度计算正确

5. **test_analyze_convergence_converged**
   - 验证能检测到已收敛状态

6. **test_analyze_convergence_diverging**
   - 验证能检测到发散状态

7. **test_compute_roi**
   - 验证能正确计算 ROI
   - 验证除零保护

8. **test_predict_convergence_point**
   - 验证能预测收敛点
   - 验证无法预测时返回 None

9. **test_is_worth_continuing**
   - 验证 ROI > 0 时返回 True
   - 验证发散时返回 False

---

## 4. Phase 3: RSIMetrics

### 4.1 核心思想

RSI 必须是可观测的，人类需要能够理解和审计每层递归的改进。

### 4.2 公共接口

```python
class RSIMetrics:
    """RSI 监控指标管理器"""
    
    # 7 个核心指标
    RSI_CYCLES_TOTAL = "rsi_cycles_total"
    RSI_IMPROVEMENT_RATE = "rsi_improvement_rate"
    RSI_CONVERGENCE_ROI = "rsi_convergence_roi"
    RSI_ROLLBACK_COUNT = "rsi_rollback_count"
    RSI_CANDIDATES_GENERATED = "rsi_candidates_generated"
    RSI_CANDIDATES_PRUNED = "rsi_candidates_pruned"
    RSI_GATE_FAILURES = "rsi_gate_failures"
    
    def __init__(self):
        """初始化 RSI 监控指标管理器"""
    
    def record_metric(self, metric_name: str, value: float) -> None:
        """
        记录指标
        
        Args:
            metric_name: 指标名称
            value: 指标值
        """
    
    def get_metric(self, metric_name: str) -> Optional[float]:
        """
        获取指标值
        
        Args:
            metric_name: 指标名称
            
        Returns:
            Optional[float]: 指标值，如果不存在返回 None
        """
    
    def check_alerts(self) -> List[Alert]:
        """
        检查告警规则
        
        Returns:
            List[Alert]: 触发的告警列表
        """
    
    def get_dashboard_data(self) -> Dict[str, Any]:
        """
        获取仪表盘数据
        
        Returns:
            Dict[str, Any]: 仪表盘数据
        """
```

### 4.3 告警规则

| 级别 | 条件 | 描述 |
|------|------|------|
| **INFO** | RSI 循环完成 | 正常运行信息 |
| **WARNING** | ROI < 0.1 | 需要关注但不紧急 |
| **ERROR** | 连续 3 次失败 | 需要人工干预 |
| **CRITICAL** | 检测到发散 | 立即停止 RSI |

### 4.4 测试计划

**测试文件**: `tests/unit/test_rsi_metrics.py`

**测试用例**:

1. **test_initialization**
   - 验证能正确初始化
   - 验证所有指标初始化为 0

2. **test_record_metric**
   - 验证能正确记录指标
   - 验证重复记录更新值

3. **test_get_metric**
   - 验证能获取指标值
   - 验证不存在的指标返回 None

4. **test_check_alerts_info**
   - 验证 INFO 级别告警

5. **test_check_alerts_warning**
   - 验证 WARNING 级别告警

6. **test_check_alerts_error**
   - 验证 ERROR 级别告警

7. **test_check_alerts_critical**
   - 验证 CRITICAL 级别告警

8. **test_get_dashboard_data**
   - 验证能生成仪表盘数据

---

## 5. Phase 4: RSIRollbackManager

### 5.1 核心思想

RSI 风险较高，必须具备自动回滚机制。

### 5.2 公共接口

```python
class RSIRollbackManager:
    """RSI 回滚管理器"""
    
    def __init__(self, max_rollback_history: int = 100):
        """
        初始化回滚管理器
        
        Args:
            max_rollback_history: 最大回滚历史记录数
        """
    
    def create_snapshot(self, system_state: Dict[str, Any]) -> str:
        """
        创建系统状态快照
        
        Args:
            system_state: 系统状态
            
        Returns:
            str: 快照 ID
        """
    
    def should_rollback(self, metrics: Dict[str, Any]) -> bool:
        """
        判断是否应该回滚
        
        Args:
            metrics: 当前指标
            
        Returns:
            bool: 是否应该回滚
        """
    
    def execute_rollback(self, snapshot_id: str) -> bool:
        """
        执行回滚到指定快照
        
        Args:
            snapshot_id: 快照 ID
            
        Returns:
            bool: 是否成功回滚
        """
    
    def get_rollback_history(self) -> List[Dict[str, Any]]:
        """
        获取回滚历史
        
        Returns:
            List[Dict[str, Any]]: 回滚历史记录
        """
```

### 5.3 测试计划

**测试文件**: `tests/unit/test_rsi_rollback_manager.py`

**测试用例**:

1. **test_initialization**
   - 验证能正确初始化

2. **test_create_snapshot**
   - 验证能创建快照
   - 验证快照 ID 唯一

3. **test_should_rollback_true**
   - 验证发散时返回 True

4. **test_should_rollback_false**
   - 验证正常时返回 False

5. **test_execute_rollback**
   - 验证能执行回滚
   - 验证回滚后状态正确

6. **test_execute_rollback_invalid_snapshot**
   - 验证无效快照 ID 返回 False

7. **test_get_rollback_history**
   - 验证能获取回滚历史

---

## 6. Phase 5: RSIDeploymentController

### 6.1 核心思想

RSI 风险较高，必须采用渐进式部署，从被动观察到完全自动化。

### 6.2 部署阶段

| 阶段 | 名称 | 描述 | 验收标准 |
|------|------|------|----------|
| Phase 0 | 观察 | 只收集数据，不执行优化 | 数据收集正常 |
| Phase 1 | 手动 | 生成优化建议，人工审批 | 建议合理率 > 80% |
| Phase 2 | 半自动 | 低风险优化自动执行 | 自动执行成功率 > 90% |
| Phase 3 | 有条件自动 | 中风险优化自动执行 | 连续 7 天无回滚 |
| Phase 4 | 完全自动 | 所有优化自动执行 | 连续 30 天无回滚 |

### 6.3 公共接口

```python
class RSIDeploymentController:
    """RSI 部署控制器"""
    
    PHASE_0_OBSERVATION = 0
    PHASE_1_MANUAL = 1
    PHASE_2_SEMI_AUTO = 2
    PHASE_3_CONDITIONAL_AUTO = 3
    PHASE_4_FULL_AUTO = 4
    
    def __init__(self, initial_phase: int = 0):
        """
        初始化部署控制器
        
        Args:
            initial_phase: 初始阶段
        """
    
    def get_current_phase(self) -> int:
        """
        获取当前部署阶段
        
        Returns:
            int: 当前阶段
        """
    
    def can_auto_execute(self, risk_level: str) -> bool:
        """
        判断是否可以自动执行
        
        Args:
            risk_level: 风险级别 ('low', 'medium', 'high')
            
        Returns:
            bool: 是否可以自动执行
        """
    
    def evaluate_phase_transition(self, metrics: Dict[str, Any]) -> bool:
        """
        评估是否应该进入下一阶段
        
        Args:
            metrics: 当前指标
            
        Returns:
            bool: 是否应该进入下一阶段
        """
    
    def advance_phase(self) -> int:
        """
        进入下一阶段
        
        Returns:
            int: 新的阶段
        """
```

### 6.4 测试计划

**测试文件**: `tests/unit/test_rsi_deployment_controller.py`

**测试用例**:

1. **test_initialization**
   - 验证能正确初始化
   - 验证默认阶段为 Phase 0

2. **test_can_auto_execute_phase_0**
   - 验证 Phase 0 不能自动执行

3. **test_can_auto_execute_phase_2**
   - 验证 Phase 2 可以自动执行低风险优化

4. **test_evaluate_phase_transition**
   - 验证能评估阶段转换

5. **test_advance_phase**
   - 验证能进入下一阶段
   - 验证不能超过 Phase 4

---

## 7. Phase 6: RSIDashboard

### 7.1 核心思想

为 RSI 提供实时监控界面。

### 7.2 公共接口

```python
class RSIDashboard:
    """RSI 仪表盘"""
    
    def __init__(self, metrics: RSIMetrics, convergence_analyzer: ConvergenceAnalyzer):
        """
        初始化仪表盘
        
        Args:
            metrics: RSI 监控指标管理器
            convergence_analyzer: 收敛性分析器
        """
    
    def get_overview(self) -> Dict[str, Any]:
        """
        获取概览数据
        
        Returns:
            Dict[str, Any]: 概览数据
        """
    
    def get_convergence_chart(self) -> Dict[str, Any]:
        """
        获取收敛性趋势图数据
        
        Returns:
            Dict[str, Any]: 趋势图数据
        """
    
    def get_gate_pass_rate(self) -> Dict[str, Any]:
        """
        获取棘轮门通过率
        
        Returns:
            Dict[str, Any]: 通过率数据
        """
    
    def get_candidate_statistics(self) -> Dict[str, Any]:
        """
        获取候选方案统计
        
        Returns:
            Dict[str, Any]: 统计数据
        """
    
    def get_rollback_history(self) -> List[Dict[str, Any]]:
        """
        获取回滚历史
        
        Returns:
            List[Dict[str, Any]]: 回滚历史记录
        """
```

### 7.3 测试计划

**测试文件**: `tests/unit/test_rsi_dashboard.py`

**测试用例**:

1. **test_initialization**
   - 验证能正确初始化

2. **test_get_overview**
   - 验证能获取概览数据

3. **test_get_convergence_chart**
   - 验证能获取趋势图数据

4. **test_get_gate_pass_rate**
   - 验证能获取通过率数据

5. **test_get_candidate_statistics**
   - 验证能获取统计数据

6. **test_get_rollback_history**
   - 验证能获取回滚历史

---

## 8. 文件结构

```
neurova/evolution/rsi/
├── __init__.py                      # 模块导出
├── recursive_ratchet_pruner.py      # 递归棘轮剪枝器（已实现）
├── integration_manager.py           # RSI 集成管理器（Phase 1）
├── convergence_analyzer.py          # 收敛性分析器（Phase 2）
├── metrics.py                       # RSI 监控指标（Phase 3）
├── rollback_manager.py              # RSI 回滚管理器（Phase 4）
├── deployment_controller.py         # RSI 部署控制器（Phase 5）
└── dashboard.py                     # RSI 仪表盘（Phase 6）

tests/unit/
├── test_rsi_integration_manager.py    # Phase 1 测试
├── test_convergence_analyzer.py       # Phase 2 测试
├── test_rsi_metrics.py                # Phase 3 测试
├── test_rsi_rollback_manager.py       # Phase 4 测试
├── test_rsi_deployment_controller.py  # Phase 5 测试
├── test_rsi_dashboard.py              # Phase 6 测试
├── test_rsi_orchestrator.py           # Phase 7 测试 (RSIOrchestrator)
├── test_closed_loop_feedback.py       # Phase 8 测试 (闭环反馈接口)
└── test_rsi_agent_integration.py      # Phase 8 测试 (Agent 集成)
```

---

## 9. 开发进度

| Phase | 模块 | 状态 | 测试数 | 通过数 |
|-------|------|------|--------|--------|
| 1 | RSIIntegrationManager | ✅ 已完成 | 5 | 5 |
| 2 | ConvergenceAnalyzer | ✅ 已完成 | 14 | 14 |
| 3 | RSIMetrics | ✅ 已完成 | 9 | 9 |
| 4 | RSIRollbackManager | ✅ 已完成 | 8 | 8 |
| 5 | RSIDeploymentController | ✅ 已完成 | 9 | 9 |
| 6 | RSIDashboard | ✅ 已完成 | 6 | 6 |
| 7 | RSIOrchestrator（编排器） | ✅ 已完成 | 7 | 7 |
| 8 | 闭环反馈接口 + Agent 集成 | ✅ 已完成 | 27 | 27 |

**总计**: 85 个测试用例（66 RSI + 19 闭环集成）

### 闭环断裂点修复总结（Phase 7-8）

| 断裂点 | 问题 | 修复方案 | 状态 |
|--------|------|----------|------|
| 1 | 没有 RSI 主循环 | 创建 `orchestrator.py` — RSIOrchestrator 编排器 | ✅ |
| 2 | 四个闭环缺少 `get_feedback()` | 为 SleepConsolidation、EmotionModule、ExperienceFeedback、ToolMemoryIntegration 添加 `get_feedback()` 方法 | ✅ |
| 3 | Agent 没有集成 RSI | 在 `agent_core.py` 初始化 RSI 编排器，PostChatPipeline 添加 RSI 迭代步骤 | ✅ |
| 4 | 没有自动优化逻辑 | RSIOrchestrator.run_iteration() 自动收集反馈 → 生成优化 → 应用优化 | ✅ |
| 5 | 没有定时任务 | RSI 迭代在每次对话后自动触发（PostChatPipeline step 11） | ✅ |

### 修改文件清单

| 文件 | 修改类型 | 说明 |
|------|----------|------|
| `neurova/evolution/rsi/orchestrator.py` | 新建 | RSIOrchestrator 编排器 |
| `neurova/evolution/rsi/__init__.py` | 修改 | 导出 RSIOrchestrator |
| `neurova/cognitive_layers/memory_layer/sleep.py` | 修改 | 添加 `get_feedback()` + RSI 参数 |
| `neurova/cognitive_layers/memory_layer/modules/emotion_module.py` | 修改 | 添加 `get_feedback()` + 情感保护计数 |
| `neurova/evolution/experience_feedback.py` | 修改 | 添加 `get_feedback()` + RSI 参数 |
| `neurova/cognitive_layers/memory_layer/tool_memory_integration.py` | 修改 | 添加 `get_feedback()` + RSI 参数 |
| `neurova/agent_core.py` | 修改 | 初始化 RSI 编排器 + `_NullSystem` |
| `neurova/post_chat_pipeline.py` | 修改 | 添加 step 11 RSI 迭代 |
| `tests/unit/test_rsi_orchestrator.py` | 新建 | RSIOrchestrator 测试 (7) |
| `tests/unit/test_closed_loop_feedback.py` | 新建 | 闭环反馈接口测试 (13) |
| `tests/unit/test_rsi_agent_integration.py` | 新建 | Agent 集成测试 (14) |

---

## 10. 参考文档

- [RSI 架构设计文档 v1.3](./21-recursive-self-improvement.md)
- [RSI v1.3 更新总结](./21-recursive-self-improvement-v1.3-summary.md)
- [RSI 集成总结](./RSI_INTEGRATION_SUMMARY.md)
- [RSI 最终总结](./RSI_FINAL_SUMMARY.md)

---

**最后更新**: 2026-06-08 07:30  
**维护者**: AI Assistant