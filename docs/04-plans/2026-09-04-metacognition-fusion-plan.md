# 元认知四套融合 · 一步到位方案

> 日期：2026-09-04
> 前提：系统未运行（无线上流量/无兼容包袱），一次性完成 A/B/C/D 四套元认知实现的收口融合。
> 方法论：红绿灯 TDD（先写锁定测试再编码）+ 修复教义（根因处修复、禁止表面抹除、Live-verify）。

---

## 0. 问题回顾（审计结论）

| 套 | 位置 | 现状 | 测试锁定 |
|----|------|------|----------|
| A 反思引擎（709行） | `cognitive_layers/meta_cognition_layer/meta_cognition.py` | 零实例化死代码，自带平行存储 | 无（可自由改造） |
| B 认知负荷 | `cognitive_layers/memory_layer/meta_cognition.py` | 唯一活链路（管线每轮喂数→巩固触发），状态不落库、无API | `test_meta_cognition_loop.py` 4用例 |
| C 事件记录器 | `memory_layer/modules/meta_cognition_module.py` | manager.meta_* 的假反思后端（record_event 只数事件） | `test_manager_full_delegation.py` 13用例 + `test_misc_audit2_bugfix.py` |
| D API stub | `api/endpoints/metacognition_api.py` | 进程内存 `_RECORDS`、无鉴权、前端唯一数据源 | 无 |

四套之间零引用、零数据流（已 grep 证实）。前端 MetacognitionPage 有四处字段契约错位，除手动创建的内存回声外全部恒空。

**关键侦察结论：**
- A 分析器期望的 `tool_history`（get_usage_stats/find_tool_pairs/get_degraded_tools/detect_anomalies）在现有代码中**无任何供给方** → 不能假设注入即可用，必须自建数据源。
- `data/` 目录已有多个独立 SQLite 库的先例（experience_knowledge.db / knowledge.db 等）→ `data/metacognition.db` 符合惯例。
- `meta_cognition_layer/__init__.py` 已修复为显式导出 growth_log/question_queue，含 PEP 562 惰性导出 → 新模块可安全顶层导出。
- `tests/unit/cognitive_layers/memory_layer/test_manager_full_delegation.py` 锁定 manager.meta_* 13 个方法必须委托到 MetaCognitionModule → **C 的类名和公开 API 必须保留**。

---

## 1. 目标架构

**单一事实源（账本）+ 投影 + 效应器**（CQRS-lite），不是 God class，不是同步漏斗。

```
写入面（唯一写口 = MetaLedger.record_*）
  chat 管线 RSI 步 ──轮次指标──▶ write_state + write_event
  tool_executor ────工具结果──▶ write_event(process_type="tool")
  A 反思引擎 ──────分析报告──▶ write_record(type=…, metadata.trigger=…)
  C MetaCognitionModule（写穿透）─事件─▶ write_event
  前端手动创建(D POST) ──────▶ write_record
              │
              ▼
     MetaLedger（per-agent 单例, RLock, SQLite 落底 + 内存热窗）
     data/metacognition.db：meta_events / meta_records / meta_states 三表
              │
    ┌─────────┼──────────────┐
    ▼         ▼              ▼
  负荷投影    统计投影       反思引擎(A 分析器, 间隔门控)
  (B 状态机)  (C 语义)       读台账 → ReflectionReport → write_record
    │                          │
    ▼                          ▼
  should_consolidate ─▶ idle_tracker.trigger_consolidation（记忆巩固/睡眠整理，现有链路不动）
                               │
                               ▼
                    读面：/v1/metacognition（D 重写）+ /v1/memory/meta/*（memory 委托）
                               ▼
                    前端 MetacognitionPage（四处契约修正 + 真字段）
```

**边界三原则（防再分裂）：**
1. 元认知只观察和建议，不动手——巩固仍归 idle_tracker，技能改进仍归 evolution，管道只发触发信号+写证据。
2. growth_log 是叙事性成长记录（链路已真），反思报告不镜像不复制，二者读各自来源；元认知报告只落台账。
3. 系统遥测（CPU/内存）已有 /monitor 域，A 的 psutil 采集**砍掉不接线**；负荷分只用认知指标（B 的四因子公式）。

---

## 2. 统一数据契约（核心决策）

### 2.1 台账三表（SQLite，均带 agent_id 列 + 索引）

```sql
-- C 语义的原始事件（process 统计、异常检测的数据源）
meta_events(id TEXT PK, agent_id TEXT, process_type TEXT, description TEXT,
            duration_ms REAL, success INT, metadata JSON, created_at TEXT)
            INDEX(agent_id, created_at)  -- 保留最近 2000 条/agent，超出裁剪

-- 面向前端的记录（手动创建 + 反思报告，统一入口列表）
meta_records(id TEXT PK, agent_id TEXT, kind TEXT,        -- thought | reflection
             type TEXT,            -- self_assessment | strategy | monitoring | planning
             content TEXT, context TEXT, confidence REAL,
             metadata JSON,        -- 反思报告: {trigger, observations[], insights[], action_items[]}
             created_at TEXT)      -- 保留最近 1000 条/agent

-- B 语义的认知负荷快照（负荷历史/趋势图数据源）
meta_states(id TEXT PK, agent_id TEXT, load_level TEXT, load_score REAL,
            active_tasks INT, memory_usage REAL, response_time_ms REAL,
            error_rate REAL, metadata JSON, created_at TEXT)
            -- 写穿透节流：仅 load_level 变化时 或 每 10 轮落一行，防止每轮写放大
```

### 2.2 对外 API 契约（前后端一次对齐，这是修四处错位的基准）

- `GET /v1/metacognition/{agent_id}/metacognition?page&size&type`
  → `{code:0, data:{items:[{id,type,content,context,confidence,created_at}], total}}`
- `POST /v1/metacognition/{agent_id}/metacognition` body `{type,content,context,confidence}` → 落库记录（**新增鉴权**：`get_current_user_or_default`，未登录 401）
- `GET /v1/metacognition/{agent_id}/metacognition/stats`
  → `data:{total_entries, by_type:[{type,count}], avg_confidence, recent_trend:[{date,count}](近7天)}`（**字段重命名以前端契约为准**：total_entries/by_type/recent_trend，废弃 total_records/categories）
- `GET /v1/metacognition/{agent_id}/metacognition/state`（**新增**）
  → `data:{load_level, load_score, active_tasks, memory_usage, response_time_ms, error_rate, updated_at}` —— B 状态机的真实现状
- `GET /v1/metacognition/{agent_id}/metacognition/history`（**新增**）
  → `data:{items:[{created_at, confidence, trigger, summary}]}` —— 反思报告时间线
- `POST /v1/metacognition/{agent_id}/metacognition/reflect`（**新增**）—— 手动触发一轮真反思，返回报告
- `/v1/memory/{agent_id}/metacognition` 与 `/v1/memory/{agent_id}/metacognition/stats`（memory 包里那两个读不存在属性 `metacog_manager` 的僵尸路由）：**同源委托台账**，返回与上相同 shape —— 同根因命中点一并修复（修复教义第5条）。

---

## 3. 四套处置明细

### A（反思引擎）— 取分析逻辑，舍平行存储与 psutil
文件 `meta_cognition_layer/meta_cognition.py` 原地改造（保留类名与 dataclasses，避免潜在 duck-typing 断裂）：
- **取**：`_analyze_tool_usage`（成功率阈值 0.7/0.95 判据）、`_detect_tool_anomalies`、`_evaluate_tool_selection_quality`、`_calculate_reflection_score`、`_generate_insights`、`_extract_task_patterns` —— 全部改为**从台账读数据**（见下），不再依赖注入 tool_history。
- **舍**：`_collect_health_metrics`（psutil，与 /monitor 重复）、`_health_metrics/_reflection_reports/_optimization_reports/_skill_reports` 四个自持列表（报告只写台账）、`write_tool_insight_to_memory`（无人调用的断轴）。
- **新增**：
  - `get_meta_engine(agent_id)` 模块级单例工厂（对齐 B 的 `get_meta_cognition` 惯例）；
  - `reflect()` 重写为真实现：台账 `meta_events` 近窗口聚合 → 工具成功率/异常/质量分 → 结合 B `get_state()` 负荷 → 产出 ReflectionReport → `write_record(kind="reflection")`；
  - `should_reflect()` 保留原间隔门控（600s）。
- `models.py`（183行，零引用）删除。

**tool_history 无供给方的解法（关键决策）**：tool_executor 执行后向台账 `write_event(process_type="tool", description=tool_name, success=…, duration_ms=…)`，A 的分析器从 `meta_events` 按工具名聚合出成功率/调用对。自包含、零新依赖、顺带让 C 的 process 统计也获得真实工具事件。

### B（认知负荷）— 原样保留，加写穿透
- 公开 API `get_meta_cognition/update_state/get_state/should_consolidate` **一行不动**（`test_meta_cognition_loop.py` 锁定）。
- `update_state()` 尾部加节流落库：`load_level` 变化或每 10 轮 → `ledger.write_state(state.to_dict())`。
- `get_meta_cognition` 的单例注册表加 `reset_meta_cognition()`（已存在，测试在用）不变。

### C（事件记录器）— 原样保留为 facade，加写穿透
- 公开 API（record_event/start_process/end_process/get_stats/get_process_stats/get_recent_events…）**一行不动**（manager 委托 13 测试锁定）。
- `record_event()` 与 `end_process()` 落事件处各加一行 `ledger.write_event(event.to_dict() + agent_id)`。agent_id 来源：MetaCognitionModule 构造时新增可选参数 `agent_id="default"`（默认值保底，manager 实例化处传入真实 agent_id）。
- `_events` 内存热窗保留（读路径性能），台账是持久真相。

### D（API stub）— 路由面保留，`_RECORDS` 死刑
- `metacognition_api.py` 全部 handler 重写为台账读写；新增 state/history/reflect 三个端点；全部挂 `Depends(get_current_user_or_default)`。
- 响应字段按 §2.2 契约输出（以前端为准重命名）。
- 现有 `{items,total,page,size}` 分页语义保留（前端已按此分页）。

### memory 包 `/meta/*` 假反思根治
- `memory_layer/manager.py` 的 `meta_reflect`：保留对 `module.record_event` 的委托（13 测试锁定的契约），**其后追加** `get_meta_engine(agent_id).reflect()`（无台账数据时自然产出空报告，不破坏锁定测试）——假反思变真反思。
- `meta_get_health_report/meta_get_reflection_report`：从 module 统计改为**台账投影**（近期事件 + 反思报告）。
- `meta_should_*` 四个门控：改为台账时间戳门控（自上次 reflect 起算间隔），module 只留兜底。
- `memory/metacognition.py` 两个 agent 级路由：删除 `getattr(agent, "metacog_manager", None)` 幽灵属性读取（该属性全仓无定义，恒 None），直接 `get_meta_ledger(agent_id).list_records/stats`。

---

## 4. 五大消费者接线核对（逐一闭环）

| 消费者 | 接线 | 状态 |
|--------|------|------|
| 自我监控 | 管线 RSI 步每轮 `update_state`（已有）+ tool_executor 写工具事件（新增一行） | 闭环 |
| 反思 | RSI 步内 `should_reflect()` 门控触发 `engine.reflect()`；API `POST …/reflect` 手动触发 | 新闭环 |
| 统计 | C 写穿透进台账；`/meta/health` 与 `/stats` 读台账投影 | 新闭环 |
| 记忆巩固 | B `should_consolidate` → `idle_tracker.trigger_consolidation`（现有，测试锁定） | 已闭环，不动 |
| 睡眠整理 | idle_tracker 内部链路（现有） | 不动 |
| 前端 UI | 见 §5 前端节 | 新闭环 |

---

## 5. 前端修正（一步到位含 UI）

`NeurUI/src/api/modules/metacognition.ts`：
- `MetacognitionStats` 对齐 §2.2（total_entries/by_type/avg_confidence/recent_trend）；
- 新增 `getCognitiveState(agentId)`、`getReflectionHistory(agentId)`、`triggerReflection(agentId)`；
- `MetacognitionEntry.type` 保持 4 枚举（后端落库即用此枚举，`type` 过滤参数直接命中）。

`MetacognitionPage.vue`（四处死区块全部接到真数据）：
1. **指标卡**（现恒 '-'/0%）：改读 `/state` —— 认知负荷 load_score、负荷级别 load_level、错误率 error_rate、响应耗时 response_time_ms（B 的真实字段）。
2. **状态详情 descriptions**：同上真字段 + active_tasks/memory_usage/updated_at。
3. **认知维度卡**（现恒空）：改为**负荷四因子构成**（task 0.3 / memory 0.25 / response 0.25 / error 0.2 —— B 公式的四个归一化因子，state 接口在 metadata 里透出）。
4. **时间线表**（现恒空）：改读 `/history` —— 反思报告的 trigger/confidence/observations 摘要。
5. 统计卡/趋势图/entries 列表/创建弹窗：后端契约对齐后自然恢复，无 UI 结构改动。
6. i18n：复用现有 `metacognition.*` 键，新增 ≤6 键（loadLevel/loadScore/errorRate/activeTasks/responseTime/triggerReflect）×11 语言包严格对齐。

---

## 6. 测试计划（红灯先行）

新增：
- `tests/unit/cognitive/test_meta_ledger.py`：record/list/stats/state 落库、per-agent 隔离、裁剪上限、重启持久化（reset+重建读回）、四因子 metadata 透出。~15 用例。
- `tests/unit/api/test_metacognition_api.py`：契约 shape 锁定（items 字段名、stats 字段名与前端 TS 类型一致）、未登录 401、create→list 回环、state 端点、reflect 端点。~10 用例。
- `tests/unit/cognitive/test_meta_engine_reflect.py`：台账喂假工具事件 → reflect 产出真报告（低成功率工具被点名、报告落台账）。~6 用例。
- 前端 `src/api/modules/__tests__/metacognition.test.ts`：新契约断言。~5 用例。

必须保持绿的锁定套件（回归闸门）：
- `tests/unit/cognitive/test_meta_cognition_loop.py`（B 契约）
- `tests/unit/cognitive_layers/memory_layer/test_manager_full_delegation.py`（C 委托 13 用例）
- `tests/unit/cognitive_layers/memory_layer/test_manager_stubs_raise.py`
- `tests/unit/agent/test_misc_audit2_bugfix.py`（C start/end_process）

---

## 7. 文件变更清单（一步到位的完整批次）

| 动作 | 文件 | 预估 |
|------|------|------|
| 新增 | `cognitive_layers/meta_cognition_layer/ledger.py` | ~260 行 |
| 改造 | `cognitive_layers/meta_cognition_layer/meta_cognition.py`（A→反思引擎） | 709 → ~400 行 |
| 删除 | `cognitive_layers/meta_cognition_layer/models.py` | -183 行 |
| 重写 | `api/endpoints/metacognition_api.py`（stub→真实现+鉴权+3新端点） | 114 → ~220 行 |
| 修改 | `cognitive_layers/memory_layer/meta_cognition.py`（B 写穿透，+8 行） | +8 |
| 修改 | `cognitive_layers/memory_layer/modules/meta_cognition_module.py`（写穿透，+6 行） | +6 |
| 修改 | `cognitive_layers/memory_layer/manager.py`（meta_reflect 真实现 + 投影改台账 + agent_id 传入） | ±30 |
| 修改 | `api/endpoints/memory/metacognition.py`（两个僵尸路由接台账） | ±40 |
| 修改 | `neurova/tool_executor.py`（执行后写台账工具事件，1 处挂点） | +5 |
| 修改 | `neurova/post_chat_pipeline.py`（RSI 步内 reflect 门控触发） | +8 |
| 前端 | `api/modules/metacognition.ts` + `pages/MetacognitionPage.vue` | ±120 |
| 前端 | i18n ×11 语言包（≤6 新键） | +66 |
| 测试 | 上述 4 个新测试文件 | ~500 行 |

工程约束遵循项：agent_id 逐层透传、单例工厂 + `reset_*()`、SQLite RLock、台账路径可注入（conftest 隔离，防测试污染 data/）、新测试文件按目录纪律归位（`tests/unit/cognitive/`、`tests/unit/api/`、前端 `__tests__/`）。

---

## 8. 实施序列（同一批次内的依赖顺序）

1. **红灯**：写 §6 全部新测试（此刻必然失败）。
2. `ledger.py` 落地 → 台账测试绿。
3. B/C 写穿透（各 +6~8 行）→ 既有锁定套件仍全绿 + 台账收到数据。
4. A 改造为台账读法反思引擎 + tool_executor 挂点 → reflect 测试绿。
5. D 重写 + memory 包两处修复 + pipeline 接线 → API 测试绿。
6. 前端 ts/vue/i18n → vitest + `npm run build`(vue-tsc) 绿。
7. **Live-verify**：全量跑受影响后端套件 + 前端测试；grep 验尸——`_RECORDS`、`metacog_manager`、平行自持列表全仓零残留。

每步都有红灯→绿灯证据；批次完成即四套归一，中途任何一步中断，系统状态都优于现状（死代码未减但真链路已通）。

---

## 9. 风险与对策

| 风险 | 对策 |
|------|------|
| 每轮对话写 SQLite 造成写放大 | state 落库节流（level 变化或每10轮）；events 仅工具调用与反思时写，无轮询 |
| 台账单文件多 agent 竞争 | RLock + per-agent 索引；沿用项目 SQLite 惯例 |
| A 分析器读台账的聚合成本 | 近窗口 LIMIT 聚合（≤500 行），SQL 完成聚合而非 Python 全表 |
| manager 13 用例委托契约被误伤 | meta_reflect 保留 module 委托在前、真分析在后；委托测试零改动通过 |
| 前端 type 过滤仍不命中 | 后端落库即用前端 4 枚举，stats.by_type 同枚举，筛选闭环 |
| 测试污染 data/metacognition.db | ledger 路径可注入 + conftest 隔离夹具（仿 `_isolate_usage_history`） |

## 10. 验收标准

1. §6 新测试全绿 + 4 个锁定套件全绿 + 前端 vitest/vue-tsc 绿。
2. grep 证实：`_RECORDS` / `metacog_manager` / A 与 C 的平行自持存储 → 零残留。
3. 前端 MetacognitionPage 五个区块（指标卡/状态详情/维度卡/entries/时间线）+ 统计卡/趋势图，**每一个都有真实数据源且字段契约与后端一致**。
4. 反思是真分析：喂入低成功率工具事件后，reflect 报告点名该工具（防"记录一次 meta_reflect"式假反思回归）。
5. 未登录访问 D 端点 → 401。
