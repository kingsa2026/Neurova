# 架构审计报告: 骨架文件标注 + 规范落地审计

> **审计时间**: 2026-06-25
> **审计方法**: zoom-out (全局调用链) + improve-codebase-architecture (深模块/删除测试) + TDD (验证驱动)
> **审计范围**:
>   1. 骨架文件标注: memory_agent.py、manager.py、neu_token_manager.py、bayesian_eki
>   2. 规范对应审计: 前端 12 项统一规范、后端配置/日志/错误库统一性

---

## 第一部分: 骨架文件标注

### 1.1 文件概览

| 文件 | 行数 | 状态 | 骨架方法数 | 标注 |
|------|------|------|-----------|------|
| `neurova/memory_agent.py` | 8 | 重导出兼容层 | 0 | ⚪ 非骨架 |
| `neurova/cognitive_layers/memory_layer/manager.py` | 1031 | Facade + 大量 stub | 87+ | 🔴 重度骨架 |
| `neurova/security/neu_token_manager.py` | 554 | 完整实现 | 0 | 🟢 无骨架 |
| `neurova/cognitive_layers/memory_layer/bayesian_eki/` | 2 文件 | 简化实现 | 3 简化 + 1 空 | 🟡 轻度骨架 |

---

### 1.2 memory_agent.py — ⚪ 非骨架（重导出兼容层）

**文件路径**: `neurova/memory_agent.py`
**行数**: 8
**状态**: 纯重导出，非骨架

**分析**:
```python
"""MemoryAgent — 向后兼容重导出
实际实现已迁移到 mem_core.py (MemCore)。
保留此文件以兼容旧的导入路径。"""
# mem_core imports
```

**zoom-out 调用链**:
- 实际实现: `neurova/mem_core.py` (MemCore 类)
- 本文件: 仅保留以兼容旧的 `from neurova.memory_agent import MemoryAgent` 导入路径

**improve-codebase-architecture 评估**:
- **删除测试**: 删除此文件后，旧的导入路径会失败，但实际实现不受影响。复杂度不会重新出现在 N 个调用方 — 它只是 1 行重导出。
- **建议**: 保留（向后兼容），但在 CONTEXT.md 中标注为"已弃用路径"

---

### 1.3 manager.py — 🔴 重度骨架（87+ stub 方法）

**文件路径**: `neurova/cognitive_layers/memory_layer/manager.py`
**行数**: 1031
**状态**: Facade 模式，核心已实现，但 87+ 方法为 stub

**文件自述** (docstring 已诚实标注):
```
⚠️ 架构现状 (基于实际代码, 非设计声明):
  - 行数: ~1000 行 (非 docstring 之前声称的 ~500 行)
  - 子模块: 仅加载 EmotionModule (非声称的 12 个独立模块)
  - EventBus: 已创建但子模块未通过它注册
  - 50+ 方法为 stub, 返回空值/默认值, 标注见各方法注释
```

**骨架方法分类标注** (87+ 个 stub):

| 分类 | stub 方法数 | 方法清单 | 真实实现位置 |
|------|------------|---------|-------------|
| **Self Model** | 4 | get_self_model, update_self_model, update_user_profile, get_user_profile | ❌ 无独立模块 |
| **Meta-cognition** | 13 | meta_monitor, meta_reflect, meta_optimize, meta_evolve_skills, meta_get_health_report, meta_get_reflection_report, meta_get_skill_stats, meta_get_all_skills, meta_match_skills, meta_should_monitor, meta_should_reflect, meta_should_optimize, meta_should_evolve_skills | ❌ 无独立模块 |
| **EKI** | 10 | eki_process_task, eki_recommend_reinforcement, eki_predict_decay, eki_get_memory_strength, eki_get_statistics, eki_batch_update, eki_update_memory_from_access, eki_set_enabled, eki_get_enabled, eki_configure | ✅ `bayesian_eki/cognitive_optimizer.py` (但未接入) |
| **TKG** | 6 | tkg_add_fact, tkg_query_current, tkg_query_at_time, tkg_get_history, tkg_detect_conflicts, tkg_get_stats | ❌ 无独立模块 |
| **Working Memory** | 8 | wm_add_turn, wm_get_context, wm_compress_turn, wm_cache_plan, wm_retrieve_plan, wm_record_plan_result, wm_get_stats, wm_clear | ❌ 无独立模块 |
| **Self Commands** | 12 | self_get_commands, self_add_command, self_update_command, self_delete_command, self_get_heart_beat_tasks, self_get_due_tasks, self_add_heart_beat_task, self_update_heart_beat_task, self_record_task_run, self_delete_heart_beat_task, self_get_system_prompt_context, self_get_status | ❌ 无独立模块 |
| **Sleep** | 4 | run_light_sleep_cycle, run_rem_sleep_cycle, run_deep_sleep_cycle, run_dormant_cycle | ✅ `modules/sleep_consolidation` (但未委托) |
| **Explainability** | 2 | get_explanation_chain, visualize_chain (explain_memory 最小实现) | ❌ 无独立模块 |
| **Advanced** | 9 | get_traces_by_trigger, detect_conflict, detect_time_conflicts, detect_all_conflicts, get_conflict_summary, add_relation, get_relations, delete_relation, get_memory_graph | ❌ 无独立模块 |
| **Relation** | 3 | relate, recall_with_associations, recall_graph | ❌ 无独立模块 |
| **Auto Update** | 2 | start_auto_update, stop_auto_update | ❌ 无独立模块 |
| **Emotion (stub)** | 11 | get_emotion_summary, get_emotion_distribution, update_emotional_state, get_emotional_state, get_dominant_emotion, get_emotion_bias, apply_emotion_to_temperature, apply_emotion_to_style, get_emotion_history, reset_emotion_to_baseline, merge_with_user_emotion | ⚠️ EmotionModule 存在但未委托 |
| **Classification** | 1 | classify_memory | ❌ 无独立模块 |
| **Buffer** | 2 | get_buffer_stats, force_write | ❌ 无独立模块 |

**已完整实现的核心功能** (非骨架):
- ✅ remember/recall/search_memories (核心记忆 CRUD)
- ✅ SQLite 持久化 (_init_persistence_db/_load_from_db/_persist_memory)
- ✅ 情感分析 (EmotionModule 代理: analyze_emotion)
- ✅ 记忆温度 (update_memory_temperature/run_decay_cycle)
- ✅ 生命周期 (get_crystallized/get_hot_memories)
- ✅ Forgetting Recovery (archive_memory/recover_from_archive/get_archived_memories)
- ✅ 语义搜索 (_semantic_recall 降级到关键词匹配)

**improve-codebase-architecture 评估**:
- **深度问题**: Facade 接口宽（100+ 方法），但实现浅（87+ stub 返回默认值）。调用方无法通过接口判断哪些方法真实工作。
- **删除测试**: 删除 87+ stub 方法后，调用方需要 hasattr 或 try/except 检测 — 复杂度转移到调用方。但当前 stub 返回默认值（如 `return {"status": "ok"}`）会**掩盖错误**，调用方以为功能正常。
- **建议**: 
  1. stub 方法应抛出 `NotImplementedError` 而非返回默认值（让失败显式化）
  2. 有真实实现的 stub（EKI、Sleep）应委托到真实模块
  3. 无真实实现的 stub（Self Model、TKG、Working Memory 等）应删除，调用方用 hasattr 检测

---

### 1.4 neu_token_manager.py — 🟢 无骨架（完整实现）

**文件路径**: `neurova/security/neu_token_manager.py`
**行数**: 554
**状态**: 完整实现，无骨架

**分析**:
- 25 个 `return None/False/True` 均为**正常业务逻辑返回值**（验证失败返回 None，撤销成功返回 True 等）
- 合并后的接口完整覆盖：简单令牌、JWT 签名令牌对、黑名单、API Key 管理、线程安全、清理
- 33 个 TDD 测试全部通过

**improve-codebase-architecture 评估**:
- ✅ 深模块：小接口（公开方法），深实现（HMAC-SHA256 签名、双模式验证、线程安全）
- ✅ 已通过删除测试：删除 auth.py 死代码后，复杂度集中在单一文件，未分散到调用方

---

### 1.5 bayesian_eki — 🟡 轻度骨架（简化实现 + 未实现组件）

**文件路径**: `neurova/cognitive_layers/memory_layer/bayesian_eki/`
**文件数**: 2 (__init__.py + cognitive_optimizer.py)
**行数**: 475 (cognitive_optimizer.py)

**`__init__.py` 声称的组件 vs 实际实现**:

| 声称组件 | 实际状态 |
|---------|---------|
| EKICognitiveOptimizer (认知优化器) | ✅ 已实现 (475 行) |
| TaskValue (任务价值级别) | ✅ 已实现 (Enum) |
| ReinforcementAction (强化动作) | ✅ 已实现 (Enum) |
| 集合卡尔曼反演 - 无梯度贝叶斯推断 | 🟡 简化版 (非真正 EKI) |
| 信息增益量化 - 任务价值评估 | 🟡 简化版 (词汇丰富度 * 长度因子) |
| 嵌入式代表性采样 - 高效参数采样 | ❌ 未实现 |
| 代理模型 - 高斯过程加速计算 | ❌ 未实现 |

**cognitive_optimizer.py 中的简化/骨架部分**:

| 方法 | 状态 | 标注 |
|------|------|------|
| `_compute_information_gain` | 🟡 简化 | "简化实现：基于内容的新颖性和复杂度" — 词汇丰富度 * 长度因子，非真正信息增益 |
| `_update_with_feedback` | 🟡 简化 | "简化版EKI更新" — 用卡尔曼增益公式但非真正集合卡尔曼反演 |
| `train_surrogate` | 🟡 简化 | "简化实现：使用训练数据调整集合参数" — 非高斯过程代理模型 |
| `_flush_updates` | 🔴 空 | "当前实现实时更新，此方法用于未来扩展" — 纯空方法 |

**已完整实现的部分**:
- ✅ TaskValue/ReinforcementAction 枚举
- ✅ TaskResult/MemoryState 数据模型
- ✅ EKICognitiveOptimizer 主类结构
- ✅ 集合初始化 (_init_ensemble)
- ✅ 记忆注册 (register_memory)
- ✅ 任务处理 (process_task)
- ✅ 强化推荐 (recommend_reinforcement)
- ✅ 衰减预测 (predict_memory_decay) — 艾宾浩斯遗忘曲线
- ✅ 粒子多样性监测 (_check_and_restore_diversity) — 防 ensemble collapse
- ✅ 统计信息 (get_statistics)
- ✅ 线程安全 (threading.RLock)

**improve-codebase-architecture 评估**:
- **接口与实现差距**: `__init__.py` docstring 声称"高斯过程加速计算"，但实际未实现 — 接口承诺超过实现
- **删除测试**: 删除 bayesian_eki 后，manager.py 的 EKI stub 方法仍返回默认值 — 复杂度未集中
- **建议**:
  1. `__init__.py` docstring 应诚实标注未实现组件
  2. `_flush_updates` 空方法应删除或抛出 NotImplementedError
  3. manager.py 的 EKI stub 应委托到 cognitive_optimizer.py（已有真实实现）

---

## 第二部分: 规范对应审计

### 2.1 前端 12 项统一规范落地审计

**审计方法**: 检查 `NeurUI/src/` 下是否存在对应目录及其实际使用情况

| # | 规范要求 | 期望目录 | 实际状态 | 落地度 | 证据 |
|---|---------|---------|---------|--------|------|
| 1 | 统一函数调用库 | `src/api/` | ✅ 存在 | 🟢 良好 | 67 个 api/modules/*.ts，有 index.ts 聚合 |
| 2 | 统一事件总线 | `src/bus/` 或 mitt | ❌ 不存在 | 🔴 未落地 | 36 文件有 emit/on 但都是组件事件，无统一总线 |
| 3 | 统一状态管理库 | `src/stores/` | ⚠️ 存在 | 🟡 部分 | 仅 5 个 store (agents/app/auth/health/notifications)，82 页面多本地状态 |
| 4 | 统一UI组件库 | `src/components/` | ⚠️ 存在 | 🟡 部分 | 仅 10 个组件 (Glass* 系列)，页面直接用 Ant Design 原生组件 |
| 5 | 统一UI样式库 | `src/styles/` | ❌ 不存在 | 🔴 未落地 | 无全局样式库，样式散落在各组件 scoped style |
| 6 | 统一UI布局库 | `src/layouts/` | ⚠️ 存在 | 🟡 部分 | 仅 2 个布局 (MainLayout/ChatLayout) |
| 7 | 统一UI交互库 | `src/composables/` | ⚠️ 存在 | 🟡 部分 | 仅 3 个 composable (useAPI/usePolling/useAgentPage) |
| 8 | 统一UI动画库 | `src/animations/` | ❌ 不存在 | 🔴 未落地 | 无动画库，动画散落在组件 transition |
| 9 | 统一UI提示库 | `src/utils/message` | ❌ 不存在 | 🔴 未落地 | 59 文件直接调用 `message.success/error`，散落各页面 |
| 10 | 统一UI日志库 | `src/utils/logger` | ❌ 不存在 | 🔴 未落地 | 无前端日志库 |
| 11 | 统一UI错误库 | `src/utils/error` | ❌ 不存在 | 🔴 未落地 | 无前端错误处理库 |
| 12 | 统一UI配置库 | `src/config/` | ❌ 不存在 | 🔴 未落地 | 无前端配置库 |

**落地度统计**:
- 🟢 良好 (1): 统一函数调用库
- 🟡 部分 (4): 状态管理、组件库、布局库、交互库
- 🔴 未落地 (7): 事件总线、样式库、动画库、提示库、日志库、错误库、配置库

**关键问题**:
1. **统一事件总线缺失**: 36 个文件使用 emit/on，但都是 Ant Design Vue 组件事件或 store 事件，无跨组件事件总线（如 mitt）。组件间通信依赖 props/emit 逐层传递。
2. **统一UI提示库缺失**: 59 个页面直接调用 `message.success/error/warning/info`，无统一封装。修改提示样式需改 59 个文件。
3. **统一UI日志库/错误库缺失**: 前端无日志收集和错误处理机制，错误散落在各页面 try/catch。

---

### 2.2 后端模块库核心 + 配置/日志/错误库统一性审计

**审计方法**: 检查 `neurova/core/` 目录 + 统计绕过统一库的模块数

#### 2.2.1 后端模块库核心 — ✅ 已建

`neurova/core/` 目录有 41 个文件，模块库核心完整:

| 类别 | 文件 | 状态 |
|------|------|------|
| 模块系统 | module_lib.py, module_system.py, base_module.py, module_tracker.py | ✅ 已建 |
| 事件总线 | event_bus.py, event_bus_enhanced.py | ✅ 已建 |
| API 标准 | api_standard.py, api_router.py | ✅ 已建 |
| 配置管理 | config.py, config_manager.py, settings_manager.py | ✅ 已建 |
| 日志管理 | logger.py, log_level.py | ✅ 已建 |
| 错误处理 | error_handler.py | ✅ 已建 |
| 状态管理 | state_manager.py | ✅ 已建 |
| 其他 | service_manager.py, health_checker.py, workspace.py 等 | ✅ 已建 |

#### 2.2.2 配置库统一性 — 🔴 未统一（23 处绕过）

**统一库**: `neurova/core/config.py`, `neurova/core/config_manager.py`
**绕过情况**: 12 个文件直接使用 `os.environ.get/os.getenv`，共 23 次

| 绕过文件 | 次数 | 说明 |
|---------|------|------|
| `neurova/skills/hub_client.py` | 8 | 直接读环境变量配置 hub URL |
| `neurova/api/app.py` | 3 | 直接读环境变量配置端口/密钥 |
| `neurova/api/endpoints/console.py` | 2 | 直接读环境变量 |
| `neurova/llm/providers/secret_store.py` | 2 | 直接读环境变量存密钥 |
| `neurova/api/middleware.py` | 1 | 直接读环境变量 |
| `neurova/security/neu_token_manager.py` | 1 | 直接读 NEU_TOKEN_SECRET |
| `neurova/skills/registry.py` | 1 | 直接读环境变量 |
| `neurova/skills/market_searcher.py` | 1 | 直接读环境变量 |
| `neurova/knowledge/config.py` | 1 | 直接读环境变量 |
| `neurova/skill_system.py` | 1 | 直接读环境变量 |
| `neurova/api/endpoints/mobile_pairing.py` | 1 | 直接读环境变量 |
| `neurova/api/auth.py` | 1 | 直接读环境变量 |

**问题**: 配置散落各处，修改配置读取逻辑（如改为远程配置中心）需改 12+ 文件。

#### 2.2.3 日志库统一性 — 🔴 严重未统一（202 处绕过）

**统一库**: `neurova/core/logger.py` (提供 `get_logger()` 函数)
**绕过情况**: 100 个文件直接使用 `logging.getLogger`，共 202 次

**关键证据**:
- `logging.getLogger` 在 100 个文件中出现 202 次
- 只有 20 个文件通过 `from neurova.core.logger import` 或类似方式使用统一库
- 统一率: 20 / 120 ≈ 16.7%

**问题**:
1. `neurova/core/logger.py` 提供了结构化日志、JSON 输出、日志轮转等功能，但 83% 的模块绕过它
2. 修改日志格式/输出方式需改 100+ 文件
3. 结构化日志功能（JSON 输出）实际未生效

#### 2.2.4 错误库统一性 — 🔴 未统一

**统一库**: `neurova/core/error_handler.py`
**绕过情况**: 几乎无模块通过统一错误库处理错误

**问题**:
1. 错误处理散落在各模块的 try/except 中
2. 无统一错误码、错误响应格式
3. `neurova/core/api_standard.py` 定义了 API 标准，但错误响应未统一通过 error_handler 处理

---

## 第三部分: 改进建议（按优先级排序）

### P0 — 立即修复（骨架掩盖错误）

1. **manager.py stub 方法应显式失败**
   - 当前: 87+ stub 返回默认值（如 `return {"status": "ok"}`），掩盖功能未实现
   - 建议: 改为 `raise NotImplementedError("EKI not integrated, use bayesian_eki/cognitive_optimizer")`
   - 理由: 让失败显式化，调用方能立即发现问题

### P1 — 高优先级（规范落地）

2. **前端建立统一事件总线**
   - 创建 `NeurUI/src/bus/index.ts` (基于 mitt)
   - 所有跨组件通信通过事件总线，禁止 props 逐层传递超过 2 层

3. **前端建立统一UI提示库**
   - 创建 `NeurUI/src/utils/message.ts`
   - 封装 `message.success/error/warning/info`，59 个页面改为调用统一库
   - 便于后续修改提示样式、添加日志记录

4. **后端日志统一**
   - 100 个文件的 `logging.getLogger(__name__)` 改为 `from neurova.core.logger import get_logger; logger = get_logger(__name__)`
   - 启用结构化日志（JSON 输出）

### P2 — 中优先级（规范完善）

5. **前端建立统一UI日志库/错误库/配置库**
   - `NeurUI/src/utils/logger.ts` — 前端日志收集
   - `NeurUI/src/utils/error.ts` — 统一错误处理
   - `NeurUI/src/config/index.ts` — 前端配置

6. **后端配置统一**
   - 12 个文件的 `os.environ.get` 改为通过 `neurova.core.config` 统一读取

7. **bayesian_eki 诚实标注**
   - `__init__.py` docstring 标注未实现组件（高斯过程、嵌入式采样）
   - 删除 `_flush_updates` 空方法

### P3 — 低优先级（架构优化）

8. **manager.py EKI/Sleep stub 委托到真实模块**
   - EKI stub → 委托到 `bayesian_eki/cognitive_optimizer.py`
   - Sleep stub → 委托到 `modules/sleep_consolidation`

9. **manager.py 无实现 stub 删除**
   - Self Model、TKG、Working Memory、Self Commands 等无独立模块的 stub 应删除
   - 调用方用 hasattr 检测或迁移到独立模块

10. **前端建立统一UI样式库/动画库**
    - `NeurUI/src/styles/` — 全局样式变量/mixin
    - `NeurUI/src/animations/` — 统一动画

---

## 附录: 审计方法说明

### zoom-out (全局视角)
- 先看项目整体结构，再定位目标文件
- 分析调用链：谁调用谁，真实实现在哪里
- 避免只看单文件，忽略全局影响

### improve-codebase-architecture (深模块/删除测试)
- **删除测试**: 想象删除模块后，复杂度是否分散到 N 个调用方
- **深度评估**: 接口宽度 vs 实现深度，识别浅模块
- **诚实标注**: 接口 docstring 应反映实际实现，不夸大

### TDD (验证驱动)
- 骨架标注后，应有测试验证标注准确性
- neu_token_manager.py 合并后 33 个测试验证无骨架
- manager.py 的 87+ stub 应有测试验证其返回默认值行为

---

**审计人**: Agent (zoom-out + improve-codebase-architecture + TDD)
**最后更新**: 2026-06-25
