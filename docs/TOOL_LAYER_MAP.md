# Neurova 工具层抽象视图

## 概述

工具层是 Neurova 系统的核心执行层，负责工具的管理、执行、记忆和进化。本文档提供工具层的高层抽象视图，检查其闭环完整性。

## 核心模块地图

```
┌─────────────────────────────────────────────────────────────┐
│                      工具层 (Tool Layer)                    │
├─────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │ ToolExecutor │  │ BuiltinTools │  │ ToolRouter   │      │
│  │ (执行器)     │  │ (内置工具)   │  │ (路由器)     │      │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘      │
│         │                 │                 │               │
│         ▼                 ▼                 ▼               │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              工具执行引擎 (Execution Engine)         │   │
│  └─────────────────────────────────────────────────────┘   │
│                           │                                 │
│                           ▼                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │ ToolMemory   │  │ ToolLifecycle│  │ Evolution    │      │
│  │ (工具记忆)   │  │ (生命周期)   │  │ (进化引擎)   │      │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘      │
│         │                 │                 │               │
│         ▼                 ▼                 ▼               │
│  ┌─────────────────────────────────────────────────────┐   │
│  │            记忆层 (Memory Layer)                    │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

## 核心组件详解

### 1. ToolExecutor (工具执行器)
**文件**: `neurova/agent/tool_executor.py`
**职责**: 
- 文本工具调用解析与执行
- 肌肉记忆工具执行
- Skill/CLI/MCP 工具分派
- 工具执行后钩子

**依赖**:
- `agent_ref`: Agent 实例引用
- `_skill_registry`: 技能注册表
- `tool_router`: 工具路由器
- `tool_memory`: 工具记忆集成
- `tool_lifecycle`: 工具生命周期管理

### 2. BuiltinTools (内置工具)
**文件**: `neurova/builtin_tools.py`
**职责**:
- 内置工具参数 schema 管理
- 工具注册和发现
- 单一事实源原则

### 3. ToolMemoryIntegration (工具记忆集成)
**文件**: `neurova/cognitive_layers/memory_layer/tool_memory_integration.py`
**职责**:
- 工具使用记录
- 经验积累
- 肌肉记忆固化
- 条件反射式工具记忆

### 4. ToolLifecycleManager (工具生命周期管理)
**文件**: `neurova/evolution/closed_loop.py` (推测)
**职责**:
- 工具状态管理 (ACTIVE, DEGRADED, ARCHIVED, FROZEN)
- 工具使用统计
- 自动降级/升级

### 5. EvolutionOrchestrator (进化编排器)
**文件**: `neurova/evolution/closed_loop.py`
**职责**:
- 统一进化引擎
- 工具权重自适应
- 经验反哺
- 经验检索

## 调用关系图

### 工具执行闭环
```
用户输入 → Agent.chat() 
    ↓
ToolMemory.check_tool_memory() → 检查肌肉记忆
    ↓ (如果命中)
ToolExecutor.execute_from_memory() → 执行工具
    ↓
ToolExecutor._on_tool_executed() → 执行后钩子
    ├── ToolMemory.record_tool_usage() → 记录工具使用
    ├── ToolLifecycle.touch() → 更新生命周期
    └── SkillPacker.observe() → 技能打包观察
    ↓
EvolutionOrchestrator.on_experience_recorded() → 经验反哺
    ↓
ToolMemory.muscle_memory.record_usage() → 肌肉记忆固化
    ↓ (下次相似问题)
ToolMemory.check_tool_memory() → 条件反射式工具记忆
```

### 工具进化闭环
```
工具执行 → ToolExecutor._on_tool_executed()
    ↓
EvolutionOrchestrator.on_after_tool_execution()
    ↓
PatternMiner.mine_patterns() → 挖掘使用模式
    ↓
ToolGeneticEngine.evolve() → 遗传算法优化
    ↓
AdaptiveToolWeights.update_weights() → 更新工具权重
    ↓
ToolMemory.update_confidence() → 更新置信度
```

## 闭环检查点

### ✅ 已闭环
1. **工具执行 → 记忆记录**: `ToolExecutor._on_tool_executed()` 调用 `ToolMemory.record_tool_usage()`
2. **工具执行 → 生命周期更新**: `ToolExecutor._on_tool_executed()` 调用 `ToolLifecycle.touch()`
3. **工具记忆 → 自动执行**: `ToolMemory.check_tool_memory()` 返回 `auto_execute` 决策
4. **经验记录 → 权重更新**: `EvolutionOrchestrator.on_experience_recorded()` 更新工具权重

### ⚠️ 潜在断裂点
1. **进化引擎初始化**: `EvolutionOrchestrator` 在 `agent_core.py` 中初始化，但 `neurova/evolution/` 目录为空
2. **工具生命周期管理**: `ToolLifecycleManager` 导入路径为 `neurova.evolution`，但目录为空
3. **肌肉记忆模块**: `MuscleMemory` 导入路径为 `neurova.cognitive_layers.memory_layer.muscle_memory`，但文件未找到

## 测试覆盖

### 单元测试
- `tests/test_tool_engine.py`: ToolEngine 单元测试
- `tests/test_tool_guard_part1.py`: 工具安全测试
- `tests/test_tool_guard_part2.py`: 工具安全测试续

### 闭环测试
- `tests/test_tool_closed_loop.py`: 工具层调用 → 工具进化 → 经验积累 → 肌肉记忆闭环测试

### 测试覆盖缺口
1. 缺少 `ToolMemoryIntegration` 的独立单元测试
2. 缺少 `ToolLifecycleManager` 的独立单元测试
3. 缺少 `EvolutionOrchestrator` 的完整集成测试

## 依赖关系

### 内部依赖
```
Agent (agent_core.py)
    ├── ToolExecutor (agent/tool_executor.py)
    ├── BuiltinTools (builtin_tools.py)
    ├── ToolMemoryIntegration (cognitive_layers/memory_layer/)
    ├── ToolLifecycleManager (evolution/closed_loop.py)
    └── EvolutionOrchestrator (evolution/closed_loop.py)
```

### 外部依赖
- `neurova.cognitive_layers.memory_layer.muscle_memory`: 肌肉记忆模块
- `neurova.evolution.closed_loop`: 进化闭环模块
- `neurova.skill_system`: 技能系统

## 闭环完整性评估

### 强项
1. **工具执行流程完整**: 从工具调用到执行结果的完整流程
2. **记忆集成良好**: 工具使用记录和肌肉记忆固化
3. **钩子机制完善**: 执行前后的钩子函数
4. **测试覆盖基础**: 基本的闭环测试存在

### 弱项
1. **进化模块缺失**: `neurova/evolution/` 目录为空，但代码中大量引用
2. **肌肉记忆模块缺失**: `muscle_memory.py` 文件未找到
3. **工具生命周期模块缺失**: `ToolLifecycleManager` 无法导入
4. **循环导入问题**: `neurova.agent.__init__.py` 与 `neurova.agent_core.py` 存在循环导入
5. **集成测试不足**: 缺少端到端的闭环测试

### 测试验证结果
运行 `test_tool_closed_loop.py` 测试时发现：
1. **循环导入错误**: `ImportError: cannot import name 'Agent' from partially initialized module 'neurova.agent_core'`
2. **模块缺失错误**: `ModuleNotFoundError: No module named 'neurova.evolution.closed_loop'`
3. **测试全部失败**: 由于上述问题，所有工具闭环测试都无法运行

## 建议

### 短期修复
1. 创建 `neurova/evolution/` 模块，实现 `EvolutionOrchestrator`
2. 创建 `neurova/cognitive_layers/memory_layer/muscle_memory.py` 模块
3. 实现 `ToolLifecycleManager` 类
4. 补充缺失的单元测试

### 长期优化
1. 完善工具层的依赖注入机制
2. 增加工具层的配置管理
3. 实现工具层的监控和日志
4. 优化工具层的性能

## 结论

工具层的核心执行流程是闭环的，但存在关键模块缺失的问题。需要补全进化模块和肌肉记忆模块，才能实现完整的工具层闭环。