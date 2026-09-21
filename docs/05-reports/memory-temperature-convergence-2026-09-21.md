# 温度衰减双实现比对与收敛报告（Issue #74）

> 范围：Issue #74 点名的「主干旁 6 处成建制死码 / 坏码」。
> 纪律：`AGENTS.md` 修复教义（根因修复 / 无表面抹除 / 放大视角 / 单一事实源）。
> 生成日期：2026-09-21。本报告是**处置记录**，不代替代码事实；判定以代码为准。

---

## 一、结论

1. **两套温度衰减实现，保留 `TemperatureEngine`，退役 `TemperatureModule`。**
   `TemperatureEngine` 是唯一有生产消费者的实现（`manager.run_decay_cycle` /
   `agent_core` / `mem_core` / `sleep` / `evolution/rsi/eval_harness` 真调用），
   且模型维度完整；`TemperatureModule` 整文件零消费者、单因子、量纲不同。
2. **取长补短落地一处**：把旁支的「衰减随时间连续变化」特质，吸收进权威实现——
   原 `_calculate_curve_factor` 是 4 段常量，在 1 / 7 / 30 天处硬跳变。
3. **顺手根修一处既有红灯**：`tests/unit/memory/core/test_temperature.py::test_ebbinghaus_curve`
   （`assert 9.375 > 9.375`）的根因正是阶跃边界；连续化后该断言自然转绿。
4. **同一根因全命中点扫荡**：另 5 组零消费者整文件死码一并真删，并常驻守卫。

---

## 二、两套实现逐维比对

| 维度 | `TemperatureEngine`（保留） | `TemperatureModule`（退役） |
|------|------------------------------|------------------------------|
| 文件 | `memory_layer/temperature.py` | `memory_layer/modules/temperature_module.py` |
| 量纲 | 0–100（阈值 60/20/5） | 0–1（阈值 0.5/0.2） |
| 衰减形态 | 多因子贝叶斯：曲线因子 × 情感保护 × 饱和效应 × 重要性加权 × 关联保护 × 重要保护 | 单因子 `exp(-rate·hours)`，无任何调节维度 |
| 访问升温 | 饱和效应 + 回忆加成 + 连击倍率 + 情感加成 + 关联加成 | 常量 `+access_boost` |
| 生命周期 | 5 阶段（active/secondary/archived/deleted/crystallized） | 无 |
| 固化/豁免 | 固化不衰减、≥80 不衰减、当日不衰减 | 无 |
| 输入校验 | `_validate_temp` / `_validate_score`（NaN/Inf/越界显式抛错） | 无 |
| 并发 | `_hybrid_method` 实例/类双调用 + DCL 默认实例单例 | 仅 `RLock` |
| 生产消费者 | 6 处（含 manager 主链路） | **零** |

**判定**：保留 `TemperatureEngine`。旁支唯一优于权威之处是「连续衰减」，
该项已被吸收（见第三节）；其余各维旁支均更弱或无此能力。

---

## 三、取长补短：连续衰减曲线

原实现（4 段常量）实测跳变：

| 空闲天数 | 1.0 | 1.0001 | 7.0 | 7.0001 | 30.0 | 30.0001 |
|----------|-----|--------|-----|--------|------|---------|
| 曲线因子 | 2.0 | 1.0 | 1.0 | 0.5 | 0.5 | 0.2 |
| 相对跳变 | — | **50%** | — | **50%** | — | **60%** |

后果：两条记忆 idle 时间相差 1 微秒，衰减因子可相差一倍；且 idle=1 天与
idle=6 天取到同一因子，导致既有断言失去区分度（就是那条红灯）。

收敛实现：**对数-对数线性插值**，锚点沿用历史经验值
（1 天=2.0、7 天=1.0、30 天=0.5、90 天及以后=0.2），锚点处严格取值，
区间内连续、单调不增。语义（短期衰减快、长期衰减慢）不变，只是消除了跳变。

实测（真跑 `MemoryManager.run_decay_cycle`，起点温度 50）：

| idle 天数 | 1.5 | 6.0 | 20.0 | 60.0 |
|-----------|-----|-----|------|------|
| 衰减量 | 16.23 | 9.90 | 5.69 | 2.63 |

- idle=1.5 天衰减量 > idle=6 天（原阶跃下二者可能相等）→ 区分度恢复；
- 衰减量随 idle 天数单调不增 → 既有语义保持；
- 温度与内存态一致写回 SQLite 持久库 → 落盘链路完好。

---

## 四、6 组死码退役台账

| 退役对象 | 消费者复核 | 去向 / 理由 |
|----------|------------|-------------|
| `memory_layer/memory_layer.py` | 生产 0 / 测试仅自身 | `AgentMemoryLayer` 门面零引用；其 `run_decay_cycle` 调 `TemperatureEngine` 上不存在的同名方法（一旦被调必炸，实测返回 `{'error': ...has no attribute 'run_decay_cycle'}`）。Agent 级入口是 `manager.MemoryManager` |
| `memory_layer/modules/temperature_module.py` | 生产 0 / 测试 0 | 第二套温度衰减实现（见第二节） |
| `memory_layer/schema.py` | 生产 0 / 测试 1 | 第二套 memories DDL + FTS5 + `memory_relations` + `trigger_chains`，全仓无人建表。唯一建表点在 `manager.py` 建库路径 |
| `neurova/enhanced_context_builder.py` + `neurova/memory_rw_manager.py` | 生产 0（后者仅被前者引用）/ 测试数处 | 旧上下文/读写栈。上下文入口是 `context/` 与 `agent/chat_pipeline` |
| `memory_layer/{bm25, enhanced_retrieval, unified_reasoning_engine, proactive_recall, deletion_state_manager, forgetting_recovery, coreference_resolver, semantic_edge_filter, memory_bus, memory_field, result_processor}.py` | 生产 0，逐个按类名复核 | 见下 |

11 个零消费者模块的去向：

- `bm25` → 检索侧 BM25 由 `api/endpoints/semantic_search_api.py` 与 knowledge 域承载；
- `enhanced_retrieval` → 检索唯一入口 `neurova_recall.NeurovaRecallEngine`；
- `unified_reasoning_engine` → 推理入口在 `causal_reasoning` / `temporal_reasoner`；
- `proactive_recall` → 主动行为入口 `proactive_question.py`；
- `deletion_state_manager` → 删除状态由 `manager.forget`（soft delete）承载；
- `forgetting_recovery` → 遗忘恢复由 `modules/forgetting_recovery_module.py` 承载（manager 真调用）；
- `coreference_resolver` → 指代消解由 LLM 会话上下文承载（`chat_pipeline` 带历史轮次下发）；
- `semantic_edge_filter` → 依赖图边模型由 `dependency_graph.DependencyEdge` 承载；
- `memory_bus` → 模块注册/事件路由由 manager 的 `EventBus` 承担；
- `memory_field` → NeRF 记忆场（模块级 `import torch`，+176MB），运行时零消费方，包内惰性导出随之拆除；
- `result_processor` → `MoEMemoryRouter.retrieve` 的真实消费方是 `MoERetrieverAdapter`。

---

## 五、放大视角：连带处理

- 退役模块的**引用与测试同步清理**：删 28 个文件（16 生产 + 12 测试）。
- 依赖死模块的**孤儿脚本**（`tests/integration/_full_session.py`、`_full_session_v2.py`、
  `_postchat_integration.py`、`tests/test_memory/test_closed_loop_final.py`：零收集、
  无人 import、仅 print 自嗨）一并删除。
- 参考死模块的**存活断言迁移到生产点**：
  - `origin` 旧库迁移断言：从 `schema.py::migrate_schema` 迁到
    `MemoryManager` 持久库建库路径（真会补列的那处）；
  - `MoEMemoryRouter` 端到端断言：从经 `ResultProcessor` 迁到直接断言
    `retrieve` 返回形状（适配器实际读取的字段）。
- **归档层台账如实登记**：`docs/06-bugfix/历史悬空引用登记台账_2026-09-21.md`
  中 5 处引用因文件真删，从「迁移可达」转为「源已删除」——
  这是如实登记新出现的洞，不是把洞改写成已修复。

---

## 六、验证证据

- **TDD 红→绿**：新增 `tests/unit/cognitive_layers/memory_layer/test_temperature_single_source.py`
  先红 `5 failed / 6 passed` → 实现后 `29 passed`（含全量死码退役锁定）。
- **A/B 无新增失败**：unit 子集失败集合逐行比对，新增 0、减少 1
  （`test_ebbinghaus_curve` 已转绿）；integration 子集新增 0、减少 2。
- **受保护子集**：`1433 passed`，失败 0（此前 4 failed），31 error 为预存（与仓库既有环境相关）。
- **静态门禁**：语法 + pyflakes 未定义名 + 995 模块导入巡检全通过；`ruff` 通过。
- **live-verify**：真跑 `MemoryManager.run_decay_cycle`（真建库 + 真落盘），
  证据见第三节实测表。
