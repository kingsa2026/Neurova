# NeurFlow 工作流 IDE 化升级 Roadmap（借鉴 smart-flow）

> 文档定位：团队执行 roadmap · TDD 优先 · 三 Phase 落地
> 创建日期：2026-08-30
> 状态：草稿（已 ExitPlanMode 批准，待 P0 Step 1 启动）
> 关联：smart-flow 项目调研（[MrXujiang/smart-flow](https://github.com/MrXujiang/smart-flow)） + Neurova NeurFlow 现状调研

---

## 〇、为什么做这件事

`smart-flow` 把自己定位为"面向开发者的 AI 工作流 IDE"，主打 **AI 原生 · 可调试 · 工作流→Agent · 触发器开箱即用** 四大差异点。Neurova 的 NeurFlow 已经具备"画布 + DAG 引擎 + 24 类节点 + 实时协作"的基础，但相对成熟工作流引擎还差 **断点/单步调试、子工作流、工作流→Agent 闭环、Webhook→Workflow 触发链路、HMAC、节点级 Mock** 这 6 个核心差异化能力。

**借鉴 smart-flow 但不照搬**：smart-flow 用 FlowGram + React，Neurova 用自研 Vue3 + Ant Design Vue；smart-flow 是轻量 IDE，Neurova 应该定位为"**面向复杂 AI 系统的智能体画布**"，把记忆/情绪/晶体化/审批/SSRF 等独有优势保留，把 smart-flow 的"工作流 IDE"差异化能力补齐。

---

## 一、Phase 总览（团队执行节奏）

| Phase | 主题 | 周期估计 | 阻塞依赖 | 完成后用户感知 |
|---|---|---|---|---|
| **P0** | 调试 IDE 化（断点 + 单步 + Mock + 变量监控） | 2-3 周 | 无 | 画布可"调试模式"运行 |
| **P1** | 触发器全链路（Webhook/Cron → Workflow + HMAC + 限流） | 2-3 周 | P0 不阻塞，但与 P0 共享 ExecutionEvent 流 | 工作流可对外暴露 webhook 入口 |
| **P2** | 工作流→Agent 闭环 + 子工作流 + 版本回滚 | 3-4 周 | 依赖 P0 调试能力验收 | 画布设计师 → Agent 使用者 → 模板市场 |

> 不在 roadmap 内（明确延后）：代码沙箱节点（依赖 sandbox 模块加固）、移动端配对触发、模板市场 UI、RBAC 完整化。这些会在 P2 完成后单独评估。

---

## 二、P0：调试 IDE 化（最高 ROI）

### 2.1 目标

让用户能在画布上设置断点、单步推进、查看执行中变量、为任意节点配置 mock 输出，**从"只能跑"升级到"可调试"**。

### 2.2 设计概览

```
┌─ NodeRegistry ─────────────────────────────────┐
│  每节点定义新增 __debug_hooks__: {             │
│    "supports_breakpoint": True,                │
│    "supports_mock": True,                      │
│    "inspect_inputs": lambda config, ctx: ...   │
│  }                                              │
└────────────────────────────────────────────────┘
              ↓
┌─ ExecutionEngine.execute_breakpoint() ─────────┐
│  流式 API（async generator）：                  │
│    async for event in executor.execute_debug():│
│        if event.node_id in breakpoints:        │
│            await debug_session.wait_resume()   │
└────────────────────────────────────────────────┘
              ↓
┌─ 前端 DebugPanel.vue ──────────────────────────┐
│  - 断点列表（来自画布节点右键菜单）             │
│  - 执行中变量（订阅 ExecutionEvent.VARIABLE_SET）│
│  - 单步控制（继续 / 单步 / 跳过 / 终止）        │
│  - Mock 值编辑（节点属性面板新增 "Mock" 标签页） │
└────────────────────────────────────────────────┘
```

### 2.3 实施步骤（每步先红后绿）

#### Step 1：扩展执行事件协议
**目标文件**：`neurova/collaboration/neurflow/execution_engine.py`
**TDD 用例**：`tests/unit/neurflow/test_execution_events.py`
- **红**：`test_breakpoint_pause_emits_paused_event` —— 设置断点的节点执行前应 emit `ExecutionEventType.PAUSED` 并暂停等待
- **红**：`test_variable_set_event_includes_scope_and_value` —— `VARIABLE_SET` 事件应带 `scope`（local/global）与 `value_preview`
- **绿**：在 `ExecutionEventType` 加 `BREAKPOINT_HIT` / `STEP_ADVANCED` / `VARIABLE_SCOPED` 三个枚举；在 `_execute_single_node` 节点前后加断点检查

#### Step 2：执行器流式 API
**目标文件**：`neurova/collaboration/neurflow/execution_engine.py`
**TDD 用例**：`tests/unit/neurflow/test_execute_debug.py`
- **红**：`test_execute_debug_yields_events_in_order` —— `execute_debug()` 应该是 `AsyncIterator[ExecutionEvent]`，按拓扑顺序 yield
- **红**：`test_debug_session_can_resume_after_pause` —— 外部 `await debug_session.wait_resume()` 后执行继续
- **绿**：抽出 `DebugSession` dataclass（含 `asyncio.Event` 用于 resume/wait），`execute()` 保留旧 API 内部转 `execute_debug()`

#### Step 3：节点 Mock 字段
**目标文件**：`neurova/collaboration/neurflow/models.py` + `storage.py` + `_migrate_*` 模式
**TDD 用例**：`tests/unit/neurflow/test_node_mock.py`
- **红**：`test_node_with_mock_output_short_circuits_execution` —— 节点配置含 `mock_output` 时，执行器直接返回 mock 值，不调用真实 executor
- **红**：`test_mock_field_persists_in_db` —— `node_definitions.executor_body_json` 应兼容存 mock（schema：`{"mock_output": ..., "real_executor": ...}`）
- **绿**：`models.WorkflowNode` 加 `mock_output: Optional[Any]`；`_execute_single_node` 命中 mock 即短路；`_execute_node` 改为 `if node.mock_output is not None: return node.mock_output`

#### Step 4：API 端点
**目标文件**：`neurova/api/endpoints/neurflow_api.py`
**TDD 用例**：`tests/api/neurflow/test_debug_api.py`
- `POST /executions/{execution_id}/breakpoint` 设置断点
- `POST /executions/{execution_id}/resume` 继续（含 `step: "in" | "over" | "out"`）
- `GET /executions/{execution_id}/variables` 获取当前作用域所有变量
- `PUT /nodes/{node_id}/mock` 设置 mock 输出

#### Step 5：前端画布集成
**目标文件**：`NeurUI/src/modules/collaboration/CanvasDesignerPage.vue` + 新建 `DebugPanel.vue`
**TDD 用例**：`NeurUI/src/modules/collaboration/__tests__/DebugPanel.test.ts`
- 节点右键菜单加 "Toggle Breakpoint"
- 属性面板新增 "Mock" 标签页（输入 JSON 即可）
- 画布运行按钮分 "Run" / "Debug"
- Debug 模式新增右侧浮动面板（断点列表 + 变量树 + 单步控制）

### 2.4 验收标准
- [ ] 单元测试 100% 通过（含新增 ≥ 15 用例）
- [ ] E2E：`tests/e2e/canvas/test_workflow_debug.py` 走通"设断点→执行→暂停→检查变量→修改 mock→单步→完成"完整路径
- [ ] `Mimosa` 安全扫描过（断点 API 不暴露敏感数据）
- [ ] 文档：更新 `docs/用户指南/工作流调试指南.md`

---

## 三、P1：触发器全链路打通

### 3.1 目标

让 NeurFlow 工作流能通过 **Webhook（HMAC 签名）+ Cron 定时 + 限流** 三种方式被外部触发，形成"画布即自动化平台"的产品形态。

### 3.2 设计概览

```
   外部系统
     │ (HTTP POST + X-Hub-Signature-256)
     ↓
┌─ /v1/webhooks/{id}/receive ────────────────────┐
│  1. HMAC 校验 (hmac.compare_digest)            │
│  2. 速率限制 (token bucket per webhook_id)      │
│  3. 路由查找 (target_type: workflow | http)    │
│  4. 异步派发 WorkflowExecutor.execute()        │
└────────────────────────────────────────────────┘
              ↓
┌─ WorkflowTriggers 表 ──────────────────────────┐
│  id | workflow_id | type | config_json |        │
│       enabled | secret_hash | rate_limit | ...  │
└────────────────────────────────────────────────┘
              ↑
┌─ /v1/workflows/{id}/triggers ─────────────────┐
│  - CRUD trigger                                │
│  - 启用 Cron 触发 (绑定 scheduler.WORKFLOW)    │
└────────────────────────────────────────────────┘
```

### 3.3 实施步骤

#### Step 1：解决双引擎分裂问题
**目标文件**：`neurova/agent/scheduler.py` + `neurova/workflow/runner.py`
**背景**：scheduler 当前 `WorkflowTaskExecutor` 走老的 `WorkflowRunner`，不是 Neurflow 的 `WorkflowExecutor`。触发器必须统一打到 Neurflow 上。
**TDD 用例**：`tests/unit/agent/test_scheduler_uses_neurflow.py`
- **红**：`test_workflow_task_dispatches_to_neurflow_executor` —— 创建 `TaskType.WORKFLOW` 任务时，应通过 `get_workflow_executor()` 执行而非 `WorkflowRunner`
- **绿**：在 `WorkflowTaskExecutor.__init__` 默认接收 `executor=None`，运行时 `get_workflow_executor()` 兜底；旧 `WorkflowRunner` 路径保留但打 deprecation 日志

#### Step 2：WorkflowTrigger 模型 + 持久化
**目标文件**：`neurova/collaboration/neurflow/storage.py` + `models.py`
**TDD 用例**：`tests/unit/neurflow/test_workflow_triggers.py`
- **红**：`test_create_workflow_trigger_persists_to_db` —— `WorkflowTrigger.create()` 应写入 `workflow_triggers` 表
- **红**：`test_trigger_secret_is_hashed_in_db` —— secret 入库前必须 `hashlib.sha256`，不存明文
- 绿：新建 `workflow_triggers` 表（id / workflow_id / type / config_json / secret_hash / enabled / rate_limit / created_at / updated_at）

#### Step 3：Webhook 入站 + HMAC 校验
**目标文件**：`neurova/api/endpoints/webhooks.py`（重构，非新建）
**TDD 用例**：`tests/api/test_webhook_hmac.py`
- **红**：`test_webhook_rejects_invalid_signature` —— `X-Hub-Signature-256` 不匹配返回 401
- **红**：`test_webhook_signature_uses_constant_time_compare` —— 用 `hmac.compare_digest` 不用 `==`
- **红**：`test_webhook_dispatch_triggers_workflow_executor` —— 命中后调用 `executor.execute()` 创建 execution 并返回 202
- **绿**：现有 dict 替换为 DB-backed；新增 `POST /v1/webhooks/{id}/receive` 入站端点；HMAC-SHA256 签名校验

#### Step 4：限流器
**目标文件**：`neurova/core/trigger_rate_limiter.py`（新建）
**TDD 用例**：`tests/unit/core/test_trigger_rate_limiter.py`
- **红**：`test_rate_limiter_blocks_excess_requests` —— 每 webhook 每分钟 N 次，超额返回 429
- **红**：`test_rate_limiter_uses_token_bucket_per_key` —— 不同 webhook_id 互不影响
- 绿：参考 `neurova/llm/providers/rate_limiter.py` 用 token bucket + asyncio.Lock

#### Step 5：Cron 触发绑定
**目标文件**：`neurova/collaboration/neurflow/triggers.py`（新建）+ `scheduler.py`
**TDD 用例**：`tests/unit/neurflow/test_cron_trigger.py`
- **红**：`test_cron_trigger_creates_apscheduler_job` —— `type="cron"` 触发器创建后，apscheduler 任务列表应包含对应 job
- **红**：`test_cron_trigger_disable_removes_job` —— 禁用触发器同步移除 apscheduler job
- **绿**：`TriggerManager` 单例管理 apscheduler job；启动时从 DB 恢复所有 enabled trigger

#### Step 6：触发器 API
**目标文件**：`neurova/api/endpoints/neurflow_api.py`
- `GET /workflows/{id}/triggers` 列表
- `POST /workflows/{id}/triggers` 新建
- `DELETE /triggers/{tid}` 删除
- `POST /triggers/{tid}/fire` 手动触发（测试用）

#### Step 7：投递记录 + 审计
**目标文件**：`storage.py` 新表 `webhook_deliveries`
- 记录每次入站：webhook_id / payload_hash / signature_valid / execution_id / latency
- 提供 `GET /webhooks/{id}/deliveries` 调试面板

### 3.4 验收标准
- [ ] `curl -H "X-Hub-Signature-256: sha256=..."` 能触发工作流
- [ ] 错误签名返回 401 + 投递记录标记 `signature_valid=false`
- [ ] 超限返回 429
- [ ] Cron 触发器可在前端 UI 创建/启用/禁用
- [ ] 所有 webhook DB 化后 `test_webhooks.py` 全绿
- [ ] Mimosa 扫描：HMAC 用 `compare_digest`、`hashlib.sha256`、无明文 secret 残留

---

## 四、P2：工作流→Agent 闭环 + 子工作流 + 版本回滚

### 4.1 目标

把画布编辑器与对话 Agent 闭环打通：用户画的 workflow 一键发布成可对话的 Agent；同时支持子工作流嵌套和工作流版本/回滚，让大型工作流可拆解、可演进。

### 4.2 子任务 4.2：工作流 → Agent 闭环

#### 设计概览

```
┌─ publish 端点（重构） ──────────────────────────┐
│  POST /workflows/{id}/publish                  │
│  1. 校验 workflow 可发布                       │
│  2. 编译 WorkflowDefinition → AgentManifest    │
│     - entry_node_id (start 节点)               │
│     - input_schema (从 start.sub_blocks 推导)   │
│     - output_schema (从 end.sub_blocks 推导)   │
│     - tool_bindings (LLM 节点 → provider_id)   │
│  3. 在 agents 表新建一行（type=workflow）       │
│  4. 触发 chat agent 可调用此 agent             │
└────────────────────────────────────────────────┘
```

**实施步骤：**
- **Step 1**：扩展 `agents` 表加 `source_type: "manual" | "workflow"` 与 `workflow_id` 字段（已部分存在，需 migration）
- **Step 2**：新建 `AgentManifest` 数据模型（`neurova/agent/workflow_agent.py`）
- **Step 3**：重构 `neurflow_api.py:850` publish 端点，从"改 status"升级为"生成 manifest + 创建 agent 记录"
- **Step 4**：chat pipeline `tool_executor` 增加 `execute_workflow_agent(agent_id, message)` 路径
- **Step 5**：前端"对话"页 agent 选择器自动列出 `source_type=workflow` 的 agent
- **TDD**：`tests/unit/agent/test_workflow_agent_compile.py` + `tests/api/test_publish_workflow.py`

### 4.3 子任务 4.3：子工作流（Subflow 节点）

#### 设计概览
新增节点类型 `builtin:subflow`：
```json
{
  "type": "builtin:subflow",
  "config": {
    "workflow_id": "wf_xxx",
    "input_mapping": {"msg": "$input.query"},
    "output_mapping": {"reply": "$node.subflow_1.output"}
  }
}
```

**实施步骤：**
- **Step 1**：在 `builtin.py` 加 `BUILTIN_NODES.append(SubflowNode)` + `exec_subflow()` 复用 `WorkflowExecutor.execute()`（传 `parent_execution_id`）
- **Step 2**：DAG 校验器加循环检测（A→B→A 抛 `WorkflowValidationError`）
- **Step 3**：执行器加 `execution_depth` 字段防止无限嵌套（默认 max=5）
- **Step 4**：前端画布节点库加 "子工作流" 分类（自动列出已发布 workflow）
- **TDD**：`tests/unit/neurflow/test_subflow_node.py`（含循环检测 + 嵌套深度限制 + 父子 execution 关联查询）

### 4.4 子任务 4.4：工作流版本与回滚

#### 设计概览
```
workflows.version 当前固定 "1.0.0"
        ↓
workflow_versions 表（每次 save 触发快照）
        ↓
前端画布顶栏 "Version" 下拉 → 显示历史 → diff → 回滚
```

**实施步骤：**
- **Step 1**：`storage.py` 新建 `workflow_versions` 表（id / workflow_id / version / snapshot_json / created_by / created_at / commit_msg）
- **Step 2**：`storage.save_workflow()` 改为先快照旧版本再写入（保留最近 20 个版本）
- **Step 3**：API `GET /workflows/{id}/versions` 列表 / `POST /workflows/{id}/rollback` 回滚
- **Step 4**：前端 `CanvasDesignerPage.vue` 顶栏加版本按钮（参考 GitHub PR 风格）
- **TDD**：`tests/unit/neurflow/test_workflow_versions.py`（含快照去重 + 容量上限 + 回滚后节点引用完整性）

### 4.5 验收标准
- 发布后能在对话页直接选 workflow 当 Agent 聊
- subflow 节点可调用任意已发布 workflow（且禁止循环）
- workflow 改 5 次后仍可回滚到任一历史版本
- `agents.source_type=workflow` 命中后 chat pipeline 自动派发到 Neurflow

---

## 五、横切关注（贯穿 P0/P1/P2）

### 5.1 测试基线
- P0/P1/P2 每个 Step 必须先红后绿，**测试用例与实现同步提交**
- 测试组织：
  - `tests/unit/neurflow/` —— 执行引擎、断点、版本（≥ 30 用例）
  - `tests/unit/agent/` —— scheduler、workflow_agent（≥ 8 用例）
  - `tests/api/` —— trigger API、HMAC、debug API（≥ 12 用例）
  - `tests/e2e/canvas/` —— 调试 E2E、触发器 E2E（≥ 3 用例）
  - 前端 `NeurUI/src/**/__tests__/` —— DebugPanel、MockEditor、VersionPicker（≥ 10 用例）

### 5.2 安全
- HMAC 必用 `hmac.compare_digest`
- secret 入库必须 hash（`hashlib.sha256`）
- webhook 入站 payload 大小限制（默认 1MB，可配）
- webhook URL 走 `NEUROVA_SSRF_ALLOWLIST`
- Mimosa 扫描每 Phase 完成时跑一次

### 5.3 性能
- 调试模式流式事件，单次执行 emit ≤ 1000 事件（超出采样）
- 触发器限流用 token bucket，O(1) 内存
- 版本快照只存 diff 而非全量（>100 节点时省 80% 空间）

### 5.4 i18n
- DebugPanel、TriggerManager 涉及 5+ 字符串加 i18n key（zh-CN/en-US/ja-JP 必对齐）
- 新 API 错误信息走 `unwrap_error(envelope)` 规范

### 5.5 文档
- P0 完成：写 `docs/用户指南/工作流调试指南.md`
- P1 完成：写 `docs/用户指南/触发器配置指南.md`（含 curl + HMAC 示例）
- P2 完成：写 `docs/用户指南/工作流发布为Agent.md` + `docs/用户指南/版本管理.md`
- 更新 `docs/分析报告/smart-flow-vs-neurova.md`（执行总结）

---

## 六、文件清单（按 Phase）

### P0 新增/修改
- `neurova/collaboration/neurflow/execution_engine.py`（修改）
- `neurova/collaboration/neurflow/models.py`（修改）
- `neurova/collaboration/neurflow/node_registry.py`（修改）
- `neurova/api/endpoints/neurflow_api.py`（修改）
- `NeurUI/src/modules/collaboration/CanvasDesignerPage.vue`（修改）
- `NeurUI/src/modules/collaboration/DebugPanel.vue`（新建）
- `NeurUI/src/modules/collaboration/MockEditor.vue`（新建）
- `NeurUI/src/modules/collaboration/__tests__/DebugPanel.test.ts`（新建）
- `tests/unit/neurflow/test_execution_events.py`（新建）
- `tests/unit/neurflow/test_execute_debug.py`（新建）
- `tests/unit/neurflow/test_node_mock.py`（新建）
- `tests/api/neurflow/test_debug_api.py`（新建）
- `tests/e2e/canvas/test_workflow_debug.py`（新建）

### P1 新增/修改
- `neurova/agent/scheduler.py`（修改）
- `neurova/workflow/runner.py`（修改，加 deprecation）
- `neurova/collaboration/neurflow/storage.py`（修改，新表）
- `neurova/collaboration/neurflow/models.py`（修改，WorkflowTrigger）
- `neurova/collaboration/neurflow/triggers.py`（新建，TriggerManager）
- `neurova/api/endpoints/webhooks.py`（重构）
- `neurova/api/endpoints/neurflow_api.py`（修改，新增 trigger 端点）
- `neurova/core/trigger_rate_limiter.py`（新建）
- `tests/unit/agent/test_scheduler_uses_neurflow.py`（新建）
- `tests/unit/neurflow/test_workflow_triggers.py`（新建）
- `tests/api/test_webhook_hmac.py`（新建）
- `tests/unit/core/test_trigger_rate_limiter.py`（新建）
- `tests/unit/neurflow/test_cron_trigger.py`（新建）

### P2 新增/修改
- `neurova/agent/workflow_agent.py`（新建，AgentManifest）
- `neurova/api/endpoints/neurflow_api.py`（重构 publish）
- `neurova/agent/chat_pipeline.py`（修改，加 workflow agent 派发）
- `neurova/collaboration/neurflow/builtin.py`（修改，加 subflow 节点）
- `neurova/collaboration/neurflow/dag.py`（修改，加循环检测）
- `neurova/collaboration/neurflow/storage.py`（修改，workflow_versions 表）
- `NeurUI/src/modules/collaboration/CanvasDesignerPage.vue`（修改，版本按钮）
- `tests/unit/agent/test_workflow_agent_compile.py`（新建）
- `tests/api/test_publish_workflow.py`（新建）
- `tests/unit/neurflow/test_subflow_node.py`（新建）
- `tests/unit/neurflow/test_workflow_versions.py`（新建）

---

## 七、风险与对策

| 风险 | 影响 | 对策 |
|---|---|---|
| 双引擎分裂（WorkflowRunner vs NeurflowExecutor） | P1 触发器无法统一派发 | P1 Step 1 优先解决；旧 WorkflowRunner 加日志告警 |
| HMAC 误配导致用户工作流不可触发 | 用户感知严重 | 默认 secret 自动生成 + UI 显式提示；提供"宽松模式"开关（仅内网） |
| Debug 流式 API 改造可能影响现有 cancel/resume | 回归风险 | P0 保留 `execute()` 旧 API，内部转 `execute_debug()`；端到端测试覆盖 cancel/resume |
| 工作流版本无限增长 | DB 膨胀 | 容量上限 20；超过自动归档（移到 `workflow_versions_archive`） |
| Subflow 嵌套过深 | 栈溢出 | `execution_depth` 字段强制限制（max=5） |
| i18n 键命名冲突 | 翻译键污染 | 命名空间：`debug.*` / `trigger.*` / `workflow_version.*` |

---

## 八、不做的（明确延后）

- **代码沙箱节点**（Python/JS）：依赖 sandbox 模块加固，单独 Phase 评估
- **模板市场 UI**：需先有"我的模板"沉淀，再做社区分享
- **完整 RBAC**：当前用户隔离够用，角色/资源/审计延后
- **移动端触发**：依赖 mobile_pairing 模块稳定后再考虑
- **FlowGram 引入**：与 Vue3 + 自研画布成本不匹配，不引入

---

## 九、退出条件（每 Phase 完成定义）

**P0 退出**：用户能在画布设断点 → 运行 → 暂停 → 看变量 → 改 mock → 单步 → 完成

**P1 退出**：`curl -H "X-Hub-Signature-256: ..."` 能触发 Neurflow 工作流 + Cron UI 可用 + 限流生效

**P2 退出**：发布的 workflow 在 chat 页可作为 agent 被选中对话 + subflow 节点可调用任意已发布 workflow + 工作流可回滚到任意历史版本

---

## 十、参考链接

- smart-flow 项目：https://github.com/MrXujiang/smart-flow
- Neurova 内部现状调研（已完成）：见对话历史 + `MEMORY.md` 中各 closed-loop 状态
- 执行引擎参考：`neurova/collaboration/neurflow/execution_engine.py`
- 存储参考：`neurova/collaboration/neurflow/storage.py`
- 触发器参考：`neurova/agent/scheduler.py` + `neurova/api/endpoints/webhooks.py`