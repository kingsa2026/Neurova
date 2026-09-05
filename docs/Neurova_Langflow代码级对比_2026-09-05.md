# Neurova vs Langflow 代码级对比报告

> 日期：2026-09-05
> 对比对象：langflow-ai/langflow @ `e3abffc`（release-1.12.0，2026-09-01 merge）vs Neurova main @ `193e3498`
> 方法：langflow 克隆至 `E:/项目/langflow-compare/langflow`，主 agent 精读图引擎（lfx 包）+ 双 Explore agent 广度扫描（langflow 服务端/前端、Neurova 全链路），关键结论两处源码抽查核实。

---

## 0. 一句话总评

**Langflow 8.6 / Neurova 7.2。** Langflow 的核心竞争力不是画布 UI（这层各家都差不多），而是围绕图执行的三层"工业化"基础设施：**顶点级持久化 + 增量重放**（不重复计费）、**HITL 统一暂停/恢复契约**（节点暂停与 Agent 工具审批同协议）、**v2 工作流 API + AG-UI 标准事件流**。Neurova 的 NeurFlow 引擎在 DAG 执行、条件/循环/子流、触发器体系、垂直节点生态上已是完整可用的一线水平，但在这三层上存在代差——且 Neurova 工作流 CRUD 完全无鉴权无属主（真实安全漏洞，比任何功能差距都优先）。

---

## 1. 架构总览对照

| 维度 | Langflow 1.12 | Neurova (NeurFlow) |
|------|--------------|-------------------|
| 仓库形态 | monorepo：`src/backend`（API+服务层）+ `src/lfx`（共享执行内核，可独立 `lfx serve`）+ `src/frontend`（React）+ `src/bundles`（25+ 组件包） | 单仓：`neurova/collaboration/neurflow/`（引擎+存储+触发器）+ `neurova/api/endpoints/neurflow_api.py` + `NeurUI/src/modules/collaboration/`（Vue 画布） |
| 图引擎 | `lfx/graph/graph/base.py` 3216 行，`Graph` 类：逐顶点 build + `asyncio.gather` 层内并行 + `RunnableVerticesManager` 动态调度 | `neurflow/execution_engine.py` 1407 行，`WorkflowExecutor`：拓扑分层（`_compute_layers` L885）+ 层内 `asyncio.gather`（L535），loop 节点单独驱动 |
| 组件协议 | Python 类 `Component`（2419 行基类）：`inputs/outputs` 声明式 IO + Pydantic schema 推导（`io/schema.py` 自动生成工具 schema 给 LLM） | 26 内置节点 `exec_*` 函数 + `sub_blocks` 参数声明；垂直扩展 commerce(2045行)/drama(848行)/comfyui/custom（两级沙箱：declarative/composite） |
| 事件流 | EventManager 队列 → SSE/轮询/POLLING|STREAMING|DIRECT 三态 → v2 AG-UI 协议 | 内存环形缓冲 event_recorder（500帧×200执行 LRU）→ SSE 50ms 轮询拉取 |
| 持久化 | SQLAlchemy 22+ 表：flow/flow_version/message/transaction/vertex_build/jobs/policy_bundle/traces… | SQLite 11 表：workflows/versions/executions/checkpoints/triggers/deliveries/… |
| 前端画布 | React Flow 12（@xyflow/react），节点状态 hook `useBuildStatus` | 自研 HTML5 拖拽+SVG 连线（2682 行），`@vue-flow/*` 已装未用 |

**关键判断：两边执行模型同构**（拓扑分层+层内 gather，Neurova 的 loop 驱动甚至更明确）。差距不在"能不能执行 DAG"，在执行结果的生命周期管理。

---

## 2. Langflow 做对了而 Neurova 缺的（按含金量排序）

### 2.1 顶点级持久化 + 增量重放（最高价值）

Langflow 每个顶点 build 后可落 `vertex_build` 表（flow_id/vertex_id/valid/params/data/artifacts/timestamp，`services/database/models/vertex_builds/model.py:69`）+ 每次顶点执行记 `transaction` 表（inputs/outputs/status/target_id/error，`transactions/model.py:157`）。恢复执行时 `api/build.py:150-162`：**已构建且 round-trip 的 producer 不再重跑**——注释原话"避免 Agent 重复计费/重复输出"。

配套机制：
- frozen 顶点缓存语义（`graph/base.py:2277` `build_vertex`：非 frozen 或 loop 才 rebuild，否则查缓存直接回填 `vertex.built_object`）；
- 缓存回填失败（KeyError/finalize 异常）安全降级为 rebuild（L2306-2312）；
- `checkpoint_opaque_dropped_ids`：检查点序列化时丢掉的顶点（不可 JSON 化）在恢复时强制重跑，`build.py:140` 的 `will_run = pred_id in dropped or not pred.built`。

**Neurova 现状**：`executions.node_results_json` 只在执行终态整体落库；断点续跑（`execution_engine.py:492-515`）从内存 instance 恢复，进程重启后续跑无凭据。checkpoint 表存的是快照而非逐节点产物，事件录制器纯内存 LRU，重启即失。

**启发 P0**：Neurova 已有 `node_results_json` 和 checkpoint 表，缺的是①逐节点产物落库（含 status/started/finished/duration）②resume 时以"节点结果存在且版本匹配"为跳过判据。改动面集中在 `storage.py` + `execution_engine.resume`，不动执行模型。

### 2.2 HITL 统一契约：HumanInput 节点 ≡ Agent 工具审批

Langflow 1.12 最漂亮的设计：`flow_controls/human_input.py`（节点暂停等人工决策，决策映射为分支输出）与 `agent_helpers/tool_approval.py`（Agent 工具调用审批）**共用同一 pause/resume 协议**——`request_id`/`options`/`allowed_decisions`/`human_input_required` 契约。细节见功力：

- `request_id` 寻址：`vertex_id:run_id`，Agent 审批追加 per-pause nonce（`vertex_id:run_id:interrupt_id`），"一次 agent 多次审批，陈旧 resume 不会误命中后一次"（`run/hitl.py:43-49`）；
- 懒超时：不设后台 watchdog，恢复时比对 `paused_at + timeout_seconds`，过期答案重路由到 fallback 分支或 `__expired__` 哨兵（不取任何分支）；
- 检查点序列化安全：`serialize_value` 对不可 JSON 化对象降级为 None（而非炸掉整个检查点），且 `wire_has_opaque_drop` 检测降级发生、被降级顶点恢复时强制重跑（`checkpoint/schema.py:62-121`）；
- 反注入：恢复反序列化只 import `lfx.*` 模块，非 lfx 模块拒绝（防从存储数据导入任意模块，`_restore_model` L141-152）。

**Neurova 现状**：`human_input` 节点有 TODO（builtin.py L1656"实现真正的人工输入等待机制"），`approval` 节点与 debug 断点三套语义各自为政；断点 resume 是"节点级软暂停"一次放行全部命中（execution_engine.py L44-48 审计注释）。

**启发 P1**：定义 Neurova 统一 `PauseRequest/PauseDecision` 契约（request_id 含 nonce + allowed_actions + timeout/fallback），让 human_input 节点、approval 节点、debug 断点、（未来的）agent 工具审批共用一条恢复链路。这是 Neurova 已在 OpenClaw P0-6 做过分段审批的方向，接上即成闭环。

### 2.3 v2 工作流 API + AG-UI 标准协议

Langflow 把画布执行迁到 `POST /api/v2/workflows`（chat.py:470 注释），事件流翻译为 **AG-UI 协议**（`lfx/workflow/agui_translator.py`：EventManager 事件 → RunStarted/StepStarted/StateDelta/RunFinished 标准事件）。合同层放 lfx（`workflow/__init__.py`："langflow backend 与 lfx serve 共用一个 contract"），鉴权动作显式枚举（`actions.py` WorkflowAction.EXECUTE/READ，"router 永远不传裸 'execute' 字符串进 host.authorize 防止 authz 漂移"）。job 语义：queued/in_progress/completed/failed/cancelled/timed_out/**suspended**（`durable/models.py`，挂起是一等状态）。

**Neurova 现状**：自有事件格式 `{seq,type,node_id,data,timestamp}` 够用但私有；SSE 是 50ms 轮询拉内存 ring buffer，无 loop 唤醒；事件重启即失。

**启发 P1**：不必引入 AG-UI 全量（Neurova 前端是 Vue 不是 React），但值得偷两个点：①事件类型对齐 AG-UI 词汇（run_started/node started=step_started…），为未来生态互通留门；②SSE 从轮询改 `asyncio.Condition`/`anyio.Event` 唤醒（event_recorder 已有 attach handler 机制，加一个 wake-up 通道改动很小）。

### 2.4 Durable 执行底座（LE-1695）

`services/durable/`：DurableJob/DurableEvent（seq 有序）/DurableSignal（stop/pause/resume）/JobStatus.suspended + SQLite 落盘，与图 checkpoint（`checkpoint/store.py` 按 `(job_id,"graph")` 存 JSON）配合，**进程重启后可从 suspended 恢复**。事件日志 seq 单调 + 信号表的设计与 Neurova 自己在 WS seq/gap 落地的方案（OpenOcta P0-1）同构——Neurova 已有技术储备，只是没接到工作流引擎上。

**启发 P1**：把 executions 表升级为 job 语义（status 加 suspended）+ 事件持久化（SQLite 追加表，seq 单调），复用 Neurova 已验证的 seq/gap 模式。与 2.1 共享改动面。

### 2.5 组件参数的 Pydantic/JSON Schema 工业化

`io/schema.py`：从 Pydantic 模型自动推导 Langflow 输入控件（`schema_to_langflow_inputs`），反向从 inputs 生成工具 schema 给 LLM（`create_input_schema`，>50 个枚举项自动降级为 string 防 token 浪费 L24，`flatten_schema` 平铺 $ref/嵌套）。节点定义即工具定义，Agent 调用工作流时参数契约零手工。

**Neurova 现状**：sub_blocks 手工声明（type: input/json/slider/select），无 JSON Schema；`workflow:{id}` 工具命名空间（workflow_as_tool.py）把工作流暴露为工具，但参数 schema 是拼接出来的。

**启发 P2**：给 NodeDefinition 加可选 `input_schema`（JSON Schema），workflow_as_tool 直接透传给 LLM tool schema；sub_blocks 保留作为 UI 渲染源，schema 作为契约源。

### 2.6 其他值得记下的点

- **warm registry**：预构建图模板 deepcopy 服务热路径（endpoints.py `try_warm_run_graph`），冷启动跳过 from_payload。Neurova 每次执行都全量 `from_dict` 重建。
- **8 tracer 后端**（langfuse/langsmith/native/opik…）+ span 拓扑排序入库（span_sorting.py，PG 外键要求父 span 先插）。Neurova 只有 otel_bridge 状态查询。
- **policy bundle**：部署策略原子持久化+运行时发布（BUNDLE_API.md），执行时门控模型服务商（`arequire_model_provider_policy` 在 frozen 缓存命中前也要重授权——"被吊销的 provider 不能复用旧输出" base.py:2280-2283）。这个"缓存命中前重授权"思想对 Neurova 的 API key 治理直接可用。
- **授权 deny→404** 防 UUID 枚举（chat.py:394 ensure_flow_permission）。
- **telemetry_writer**：vertex_build 写入走磁盘 outbox 异步批量，不占请求连接池（graph/utils.py:330）。
- **AG-UI + ag_ui.core 依赖**：Langflow 已把 agent 交互协议标准化作为战略方向。

---

## 3. Neurova 领先或对等之处

| 能力 | Neurova | Langflow | 结论 |
|------|---------|----------|------|
| 垂直节点生态 | commerce/drama/comfyui 2938 行专用节点 + 26 内置 | 通用组件 100+ 目录，无垂直 | Neurova 强（langflow 靠 bundles 补） |
| 自定义节点沙箱 | 两级 declarative/composite，拒绝任意 Python | Python code 组件（执行用户代码） | 哲学不同：Neurova 安全优先，langflow 能力优先；Neurova 立场自洽，不必跟 |
| 条件表达式 | safe_eval 白名单 DSL（自研 tokenizer+递归下降，错误返回 False） | Python 表达式 | 同上，Neurova 安全面更好 |
| 触发器体系 | cron(APScheduler)/webhook(ingress+secret+deliveries+重试)/manual/plugin/agent scheduler | webhook 组件（graph 内），无 cron 触发体系 | **Neurova 显著领先** |
| 双向 agent 融合 | 工作流 publish→AgentManifest 落 agents 表可当选 Agent；`run_workflow_agent` 工具反调；`workflow:{id}` 命名空间 | 有 flow-as-tool（run_flow 组件），无 publish-to-agent | **Neurova 领先** |
| 调试器 | execute_debug 断点/单步/mock 注入/resume | Playground step-by-step（聊天面板级） | Neurova 引擎级调试更深，langflow 体验更打磨 |
| 版本管理 | 自动快照 fingerprint+保留 N 版+rollback（无 commit_msg 输入） | flow_version 表+Sidebar+Restore+预览 overlay | langflow UI 完整（含用户输入的版本说明），Neurova 后端机制已有 |
| 测试 | neurflow 76+ 用例文件（unit/api/integration） | backend tests 931 文件 | 量级差异，但 Neurova 覆盖自己的面够用 |
| NL→工作流 | CanvasNLDesigner + nl_designer.py | 无对应物 | Neurova 独有 |

---

## 4. 评分矩阵（10 分制，权重按"对工作流产品竞争力的重要性"）

| # | 维度 | 权重 | Langflow | Neurova | 说明 |
|---|------|-----|----------|---------|------|
| 1 | 图执行模型 | 12% | 9.0 | 8.5 | 同构（分层+gather）；langflow 多动态 successor 调度与 cycle 管理（MAX_CYCLE_APPEARANCES） |
| 2 | 执行结果生命周期（持久化/重放/缓存） | 15% | 9.5 | 5.0 | vertex_build+transaction+frozen 缓存 vs 终态一次性落库+内存续跑 |
| 3 | HITL/暂停恢复 | 10% | 9.0 | 4.5 | 统一契约+durable checkpoint+超时重路由 vs human_input TODO+三套语义 |
| 4 | 事件流与协议 | 8% | 8.5 | 6.0 | AG-UI 标准化+三态投递 vs 私有格式+轮询拉取（seq/gap Neurova 别处已会） |
| 5 | 组件/参数契约工业化 | 10% | 9.0 | 6.5 | Pydantic↔tool schema 双向 vs sub_blocks 手工声明 |
| 6 | 画布与调试体验 | 10% | 9.0 | 7.0 | React Flow 12+版本 UI+Playground vs 自研 SVG（vue-flow 已装未用）+版本抽屉+引擎级 debug |
| 7 | 触发与调度 | 8% | 5.0 | 8.5 | langflow 无 cron 体系；Neurova cron/webhook/重试/恢复完整 |
| 8 | Agent 融合（双向） | 8% | 6.5 | 8.5 | publish→Agent+workflow-as-tool+run_workflow_agent vs flow-as-tool 组件 |
| 9 | 安全与多租户 | 10% | 8.0 | 4.0 | authz 插件系+deny→404+provider policy vs **工作流 CRUD 无鉴权无属主** |
| 10 | 可观测性 | 5% | 8.5 | 5.5 | 8 tracer+span 库 vs otel 状态查询+duration 字段 |
| 11 | 垂直生态与差异化 | 4% | 6.0 | 8.5 | commerce/drama/NL 设计器 |
| — | **加权总分** | 100% | **8.3** | **6.7** | |

评分说明：#2/#3/#9 是本轮发现的三个代差点；#7/#8/#11 是 Neurova 的护城河。langflow 的 25+ 组件 bundles 和 931 测试文件体现的是生态与人力差距，单点技术 Neurova 无代差。

---

## 5. 启发落地清单（按性价比排序）

### P0（安全+根因级，先做）

- **P0-1 工作流鉴权与属主隔离**：`workflows` 表加 `user_id` 列 + CRUD/execute/publish/versions 全端点鉴权（现在 `neurflow_api.py:385-455` 裸奔，`GET /workflows` 连 `get_current_user_or_default` 都没有，任何认证用户可读写删全部工作流，未认证也可列表）。迁移方案：存量回填 `user_id='default'`（对齐记忆系统 scope 化先例）。deny→404 防 UUID 枚举可直接抄 langflow。**这是真实安全漏洞，优先级高于一切功能项。**
- **P0-2 节点级执行产物落库 + resume 以产物为准**：新表（或扩展 checkpoint 表）逐节点存 status/inputs/outputs/duration；`resume` 判据从内存 instance 改为"结果存在且 workflow fingerprint 匹配则跳过"。对齐 langflow 的 opaque-drop 语义：无法序列化的节点产物标记为必须重跑，不静默跳过也不静默失败。

### P1（架构对齐，中等改动）

- **P1-1 HITL 统一契约**：定义 `PauseRequest{request_id(vertex:run:nonce), kind, options, allowed_actions, timeout_at, fallback}`，human_input/approval/debug 断点三链路收敛到一条 resume API；超时用 langflow 的懒判定（无 watchdog）。
- **P1-2 事件持久化 + suspended 语义**：事件追加表（seq 单调）+ executions.status 加 suspended；SSE 改 Condition 唤醒 + 游标续传已有（`after` 参数保留）。与 P0-2 同一存储改动面，建议同批。
- **P1-3 frozen/缓存命中前重授权**：Neurova 节点若引用 LLM provider/知识库凭据，续跑/缓存命中前重校验凭据属主与有效性（langflow `arequire_model_provider_policy` 的思想），防"凭据已吊销仍用旧结果"。

### P2（体验与生态）

- **P2-1 画布切 vue-flow**：`@vue-flow/*` 已在 package.json 里装了没用，切图库后节点状态 hook 化（对标 useBuildStatus），顺手把 2682 行 CanvasDesignerPage 拆模块。
- **P2-2 NodeDefinition.input_schema（JSON Schema）**：workflow-as-tool 直接透传 LLM；>50 枚举项降级策略可抄。
- **P2-3 版本说明（commit_msg）**：快照机制已有，只差把 "auto snapshot" 换成用户输入（前端版本抽屉加输入框）。
- **P2-4 warm start**：已发布工作流预编译 WorkflowDefinition 缓存（publish 时编译一次），执行热路径跳过 from_dict。
- **P2-5 tracer 对接**：现有 otel_bridge 接 langfuse 一个后端即可（span 拓扑排序入库的坑 langflow 已踩，直接看 span_sorting.py）。

### 不建议跟进

- Python code 执行组件（与 Neurova 白名单 DSL 沙箱哲学冲突，且引入 RCE 面）；
- AG-UI 全量协议（前端栈不同，对齐词汇表即可）；
- Redis job queue（Neurova 单机定位，SQLite durable 够用）；
- 25+ bundles 拆包（人力模型不同）。

---

## 6. 复查注记

- langflow 克隆为 shallow（仅 1 commit），提交历史与 1.12 changelog 未能核对；report 中"最新特性"均以代码内 docstring/注释为证。
- 两处关键事实已二次抽查源码核实：Neurova workflows 表无 user_id 列（storage.py:57-79）且 list_workflows 无鉴权依赖（neurflow_api.py:385）；langflow resume 跳过已构建 producer（build.py:150-162）。
- Neurova 侧"冻结废弃引擎"（execution_engine/workflow_engine.py）与 FlowOrchestrator 重叠为已知架构债，本报告按 NeurFlow 唯一真引擎口径对比。
