# Bug 报告: P1 和 P2 问题修复

**日期**: 2026-06-24
**方法论**: bug-hunt (5阶段) + TDD (红绿灯) + zoom-out + improve-codebase-architecture
**测试结果**: 55/55 通过

---

## 修复概览

| 编号 | 问题 | 严重性 | 状态 | 测试数 |
|------|------|--------|------|--------|
| P1.1 | Step 9.96 死代码 (已实现未接线) | P1 | 已修复 | 4/4 |
| P1.2 | PatternCrystallizer 模式键过度简化 | P1 | 已修复 | 8/8 |
| P1.3 | MemoryManager docstring 失实 + stub 未标注 | P1 | 已修复 | 12/12 |
| P2.1 | InitializationManager 已实现未接线 | P2 | 已修复 | 10/10 |
| P2.2 | neu_token_manager 误判为骨架 | P2 | 已纠正 | 13/13 |

---

## P1.1: Step 9.96 死代码

### 根因链
```
_step_extract_conversation_rules 方法已完整实现
  → 但 process() 中未调用该方法
  → 经验规则提取功能完全失效
  → 对话中的规则模式无法被学习和关联
```

### 修复
在 `post_chat_pipeline.py` 的 `process()` 中, Step 9.95 之后、Step 10 之前插入 Step 9.96 调用。

### 文件
- `neurova/post_chat_pipeline.py` — 接线 Step 9.96
- `tests/unit/core/test_step_996_wiring.py` — 4个TDD测试

---

## P1.2: PatternCrystallizer 模式键过度简化

### 根因链
```
_extract_pattern_key 仅取 context[:50].strip()
  → 不同语义但相同前缀的模式被错误合并
  → 例如 "搜索 Python 教程" 和 "搜索 Python 安装" 共享同一模式键
  → MuscleMemory 学习到错误的模式关联
  → 闭环学习准确性下降
```

### 修复
实现基于关键词提取的模式键:
1. 分词 (正则匹配中文连续字符 + 英文单词)
2. 去停用词 (中英文停用词表)
3. 去重, 取前8个关键词
4. 用 `|` 连接作为模式键

### 文件
- `neurova/cognitive_layers/memory_layer/pattern_crystallizer.py` — 关键词提取
- `tests/unit/memory/test_pattern_crystallizer_key.py` — 8个TDD测试

---

## P1.3: MemoryManager docstring 失实 + stub 未标注

### 根因链
```
MemoryManager docstring 声称 "~500行 Facade + 12个独立模块"
  → 实际 ~1000行, 仅加载 EmotionModule
  → 50+ 方法为 stub (返回空值/默认值)
  → 调用方误以为这些方法有真实实现
  → 静默失败: 功能不工作但不报错
```

### 修复
1. 纠正顶部 docstring, 反映真实架构状态
2. 标注所有 stub 区域 (Self Model / Meta-cognition / EKI / TKG / Working Memory / Sleep / Explainability)
3. 纠正 Forgetting Recovery 为 IMPLEMENTED (之前误标为 stub)

### 文件
- `neurova/cognitive_layers/memory_layer/manager.py` — docstring + stub 标注
- `tests/unit/memory/test_manager_stub_annotations.py` — 12个验证测试

---

## P2.1: InitializationManager 已实现未接线

### 根因链
```
InitializationManager 完整实现 (Kahn拓扑排序 + DFS循环检测)
  → 但 SubSystemContainer.init_all() 仍用硬编码顺序
  → 依赖关系隐式、不显式
  → 潜在 bug: voice 在 evolution 之前初始化
    → voice_memory_bridge 获得 evolution_orchestrator=None
    → 语音记忆桥接功能静默失效
```

### 修复
1. 在 SubSystemContainer 中添加 `_build_dependency_graph()` 方法, 声明12个子系统的依赖关系
2. 添加 `_compute_initialization_order()` 方法, 使用 InitializationManager 拓扑排序
3. 重写 `init_all()`, 按拓扑排序顺序执行初始化
4. 声明 voice 依赖 [memory, evolution], 修复 evolution→voice 顺序 bug

### 依赖图
```
memory:       []
context:      [memory]
conversation: []
management:   []
voice:        [memory, evolution]  ← 修复: evolution 必须在 voice 之前
security:     []
cognition:    [memory]
evolution:    [memory, management]
tools:        [memory, management]
pipeline:     [memory, context, tools]
loop:         [pipeline]
api_keys:     []
```

### 文件
- `neurova/agent_core.py` — SubSystemContainer 接线 InitializationManager
- `tests/unit/core/test_subsystem_initialization_wiring.py` — 10个TDD测试

---

## P2.2: neu_token_manager 误判为骨架

### 根因链
```
知识图谱将 neurova/security/neu_token_manager.py 判断为骨架文件
  → 实际是完整实现 (8个方法: generate_token/validate_token/revoke_token/...)
  → 被 api/app.py:249 实际使用
  → 知识图谱失实, 误导后续分析
```

### 纠正
通过13个TDD测试验证 neu_token_manager.py 是完整实现:
- generate_token / validate_token / revoke_token 功能正常
- generate_api_key / validate_api_key / revoke_api_key 功能正常
- list_api_keys / cleanup_expired_tokens 功能正常
- api/app.py 确实导入并使用该模块

### 新发现: 重复实现
存在两个 NEUTokenManager 类:
1. `neurova/auth.py` — 更完整 (refresh token, blacklist, lifecycle callbacks)
2. `neurova/security/neu_token_manager.py` — 被 api/app.py 实际使用

两者都是完整实现, 存在架构重复。建议后续统一到一个实现。

### 文件
- `tests/unit/security/test_neu_token_manager_complete.py` — 13个验证测试

---

## 测试清单

| 测试文件 | 测试数 | 状态 |
|----------|--------|------|
| `tests/unit/core/test_on_tool_executed_signature.py` (P0) | 8 | 通过 |
| `tests/unit/core/test_step_996_wiring.py` (P1.1) | 4 | 通过 |
| `tests/unit/memory/test_pattern_crystallizer_key.py` (P1.2) | 8 | 通过 |
| `tests/unit/memory/test_manager_stub_annotations.py` (P1.3) | 12 | 通过 |
| `tests/unit/core/test_subsystem_initialization_wiring.py` (P2.1) | 10 | 通过 |
| `tests/unit/security/test_neu_token_manager_complete.py` (P2.2) | 13 | 通过 |
| **合计** | **55** | **全部通过** |

---

## 修改文件清单

| 文件 | 修改类型 | 说明 |
|------|----------|------|
| `neurova/tool_executor.py` | P0 修复 | on_tool_executed 签名 + 转发 |
| `neurova/post_chat_pipeline.py` | P1.1 修复 | Step 9.96 接线 |
| `neurova/cognitive_layers/memory_layer/pattern_crystallizer.py` | P1.2 修复 | 关键词提取模式键 |
| `neurova/cognitive_layers/memory_layer/manager.py` | P1.3 修复 | docstring + stub 标注 |
| `neurova/agent_core.py` | P2.1 修复 | SubSystemContainer 接线 InitializationManager |

---

## 后续建议

1. **NEUTokenManager 重复实现**: 统一 `auth.py` 和 `security/neu_token_manager.py` 到一个实现
2. **MemoryManager stub 方法**: 逐步实现 Sleep / Explainability / Self Model 等 stub 方法
3. **预存测试失败**: tests/unit/core/ 中有多个预存测试失败 (ACPStreamEventType, ErrorHandler, IdleTimeTracker 等签名不匹配), 与本次修复无关, 建议单独处理
