# Neurova 工作流优化实施方案（基于 Langflow 代码级对比）

> 日期：2026-09-05
> 依据：`docs/Neurova_Langflow代码级对比_2026-09-05.md`（langflow 1.12.0 @e3abffc vs Neurova @193e3498，8.3/6.7）
> 方法论：TDD 红绿灯先行；新扩展点 env 门控默认关；等价性测试锁定旧行为；每项含 live-verify 与防回归用例。

---

## 0. 总原则与批次依赖

1. **只增不降**：所有改动向后兼容，存量数据迁移（回填 `user_id='default'`，对齐知识库 scope 化先例）。
2. **先查"机制已存在缺传动轴"**：本方案多项不是新建系统，而是给已有机制接线（checkpoint 表已存在、resume 跳过逻辑已存在、resume API 已预留审批语义）。
3. **批次依赖**：Wave 0 独立可先行 → Wave 1（同存储改动面同批）→ Wave 2 依赖 Wave 1 → Wave 3 并行小批。

```
Wave 0: P0-1 鉴权属主隔离 ──────────────（独立）
Wave 1: P0-2 节点产物落库 + P1-2 事件持久化（同一 SQLite 改动面）
Wave 2: P1-1 HITL 统一契约（依赖 P0-2 checkpoint + P1-2 suspended 枚举）
        P1-3 续跑重授权（小项）
Wave 3: P2-1~5 体验项（互不依赖，可穿插）
```

---

## 1. P0-1 工作流鉴权与属主隔离（Wave 0）

### 1.1 现状与根因

- `workflows` 表无 `user_id` 列（`storage.py:57-79`），`neurflow_api.py:385-467` 的 list/create/get/put/delete/search 全部无鉴权依赖；`duplicate`(897)/`definition`(931/946)/`viewport`(974)/`publish`(992)/templates(1199-1300)/triggers CRUD(1657-1836)/versions(1838-1870) 同样裸奔。
- 对照组：`executions` 表已有 `user_id` 列+索引；`connected_stores` 已全链路按 `user_id` 隔离（storage.py:269）——隔离机制项目内已有先例，workflows 是漏网。
- execute 端点已"不再信任请求体 user_id"（L513 注释），但缺"工作流属主校验"。

### 1.2 改动点

| 文件 | 改动 |
|------|------|
| `neurflow/storage.py` | ① workflows 表加 `user_id TEXT` 列（沿用 `_existing_cols` + `ALTER TABLE ADD COLUMN` 模式，见 webhook_deliveries 先例 L195-201）；② 加 `idx_workflows_user` 索引；③ 存量回填 `UPDATE workflows SET user_id='default' WHERE user_id IS NULL`（幂等，启动时执行）；④ `list_workflows/get_workflow/update_workflow/delete_workflow` 增加 `user_id` 过滤参数，`create_workflow` 落 `user_id` |
| `neurflow/api/endpoints/neurflow_api.py` | ① 上述端点注入 `user: User = Depends(get_current_user)`；② 属主过滤：非 owner 且非 admin → **404**（不是 403，抄 langflow deny→404 防 UUID 枚举）；③ `public=1` 的工作流：登录用户可读可执行，仅 owner/admin 可改删；④ execute：已取 JWT user_id 后追加属主/ public 校验 |
| `neurflow/collaborate/workflow/scheduler.py` | cron 触发 `run_workflow` handler 以触发器属主身份执行（trigger 表补 user_id 或从 workflow 反查） |
| `neurova/agent/workflow_agent.py` | `run_workflow_agent` 已有属主校验（L112-113），补充 admin 豁免语义对齐 |

### 1.3 语义决策（实现前确认一次）

- admin 看全量（对齐 memory-settings 先例：读=登录、改删=owner 或 admin）。
- template 实例化：模板对登录用户可读，实例属主=实例化人。

### 1.4 TDD 用例（先红后绿，`tests/unit/neurflow/test_workflow_ownership.py`）

1. 匿名 GET /workflows → 401；2. 用户 A 创建 → 用户 B GET/PUT/DELETE → 404；3. owner 全链路 200；4. admin 可见全量、可改删；5. public 工作流：B 可读可执行、不可改；6. 存量迁移：预置无主行 → 启动回填 default → default 用户可见；7. deny 响应体不泄露存在性（404 与不存在同构）。

### 1.5 回归面与风险

- `tests/api/neurflow/`（publish 4 + trigger_api 9）、`test_neurflow_integration.py` 34 用例、`test_workflow_versions` 9 用例将因新鉴权变红——**预期红**，同步改 fixture（创建时带 token）后须全绿；只允许改 fixture 不允许放宽断言。
- 非 HTTP 入口三处必须走查：scheduler cron、webhook receive（匿名入口，按 trigger→workflow 属主执行）、agent scheduler。漏一处即为断链。
- 估算：后端 1 天 + 测试修正 0.5 天。

---

## 2. P0-2 节点级执行产物落库 + Resume 凭据化（Wave 1）

### 2.1 现状与根因（比对比报告初判的窄，机制大半已存在）

- `execution_checkpoints` 表**已存在**且含 node_results_json/variables_json（storage.py:206-224），`save_checkpoint` UPSERT（L1184-1226）。
- 缺口一：`_save_checkpoint` 只在 execute **入口（L404）和出口（L651）** 两个时机调用——中途节点产物不落库，进程崩溃/重启后只能从头重跑。
- 缺口二：resume 跳过判据 `res.status=="success"`（execution_engine.py:489-503）信任 node_results，但 `json.dumps` 失败时 `_save_checkpoint` 整体静默跳过（L339 except 吞掉）——**没有 langflow 的 opaque-drop 语义**：不能序列化的节点会被静默丢弃或整体不落盘，恢复后行为不可预期。
- 缺口三：无 workflow fingerprint 校验——改了图之后用旧 checkpoint 续跑会张冠李戴。

### 2.2 改动点

1. **逐节点增量落盘**：`_execute_single_node` 返回后（三态：success/failed/skipped）调用新增 `storage.save_checkpoint_node(execution_id, node_id, result, variables_delta)`——单列 UPDATE（JSON 增量合并），不做全实例序列化；失败节点同样落盘（langflow transaction 表语义：错误也是产物）。
2. **opaque-drop 语义**：`save_checkpoint_node` 内 per-node try/except，序列化失败 → 落 `{"status":"success","_opaque":true}`；engine resume 遇 `_opaque` 节点**视为未构建、强制重跑**（对齐 langflow `checkpoint_opaque_dropped_ids` → `will_run`，build.py:140-162）。禁止静默跳过。
3. **fingerprint 门**：checkpoint 行加 `workflow_fingerprint TEXT`（写时取当前定义 hash）；`execute(resume=True)` 校验不一致 → 拒绝并返回明确错误"工作流已变更，请重新执行"（新增 API 错误码，不吞）。
4. **resume 凭据链补全**：`POST /executions/{id}/resume`（neurflow_api.py:1073）当内存 instance miss 时从 `get_checkpoint`（L1872 已有只读端点）恢复 instance 再 `execute(resume=True)`——若已实现则补测试锁死该路径；未实现则为本次新增。

### 2.3 TDD 用例（`test_execution_checkpoint.py` 扩展）

1. 模拟第 2 层执行后重建 executor（新进程语义）→ resume → 仅剩余节点执行、`node_started` 事件不含已完成节点；2. 输出含不可序列化对象（lambda/自定义类）→ checkpoint 仍落盘且 `_opaque` → resume 该节点重跑；3. fingerprint 不一致 → resume 拒绝、原 checkpoint 保留；4. 失败节点产物落盘 → retry 时可见失败输入。

### 2.4 验收

live-verify：跑一个 3 层工作流，第二层后 `taskkill` 后端 → 重启 → resume → 全图完成且 LLM 节点不重复计费（token 账单核对）。净 LOC 预期 +60~90 行（新方法+判据），超出去向须在提交说明列明。

---

## 3. P1-2 执行事件持久化 + SSE 唤醒 + suspended 语义（Wave 1 同批）

### 3.1 现状与根因

- `ExecutionEventRecorder` 纯内存环形缓冲（500 帧/执行 × 200 执行 LRU，event_recorder.py:29-31），重启即失；LRU 逐出后 `snapshot` 返回空 → SSE 断流变哑（前端降级 1s 轮询兜底）。
- SSE `subscribe` 50ms 轮询拉取（L124-143），无唤醒；游标 `after` 续传只在内存内有效。
- langflow 对照：durable 事件日志 seq 单调 + job suspended 一等状态（`durable/models.py`）；Neurova 自己在 WS seq/gap（OpenOcta P0-1）已验证同构模式，属"机制已验证、未接到工作流"。

### 3.2 改动点

1. **新表 `execution_events`**：`(execution_id, seq)` 复合主键，列 type/node_id/data_json/timestamp，索引 (execution_id, seq)；`storage.append_event` 批量 flush（阈值 32 条或 1s 定时，防 SQLite 写放大——对齐 langflow telemetry_writer outbox 思想）。
2. **双写**：`record()` 仍先写内存 ring（热读不变），入 flush 队列；进程退出/终态事件强制 flush。
3. **SSE 改造**（neurflow_api.py:703-786）：`snapshot` 内存 miss 时查 DB `after` 游标续段；`subscribe` 用 `asyncio.Condition`（recorder 增 `notify_all`）替代 `asyncio.sleep(0.05)`，保留 15s keep-alive 注释帧与首帧竞态兜底。
4. **suspended 枚举**：executions/checkpoints 的 status 允许 `suspended`（本批只加枚举+存储透传+`GET /executions` 可过滤；**生产者留待 P1-1**——扩展点默认关）。

### 3.3 TDD 用例（`test_execution_event_recorder.py` 扩展）

1. 逐出 LRU 后按 after 游标从 DB 续读且 seq 连续无洞；2. flush 阈值/终态强制 flush；3. Condition 唤醒（fake clock 测量时延 < 50ms）；4. 重启模拟（新 recorder 实例 + 同 DB）→ 历史事件可回放；5. suspended 合法状态过滤。

### 3.4 风险

事件量级评估：单执行 26 节点 × 6 事件 ≈ 156 行，放大可忽略；但 loop 大迭代需设 per-execution 事件上限（10000 行截断+告警标记，登记台账）。

---

## 4. P1-1 HITL 统一暂停/恢复契约（Wave 2，依赖 P0-2+P1-2）

### 4.1 现状与根因（三条链路三套语义）

- `exec_human_input`（builtin.py:1651-1660）：TODO stub，直接返回 timeout。
- `exec_approval`（L2065-2160）：channel 广播 + `threading.Event` **同步阻塞**在节点执行器内等关键词回复——占住工作协程、超时内不可取消、无持久化（重启即丢）。
- debug 断点：内存软暂停，一次 resume 放行全部命中（execution_engine.py L44-48 审计注释）。
- langflow 对照：HumanInput 节点与 Agent 工具审批共用 `request_id/options/allowed_decisions` 协议，懒超时（恢复时比对，无 watchdog 线程）、per-pause nonce 防陈旧恢复、暂停即落 durable checkpoint（`run/hitl.py` 全链）。

### 4.2 契约定义（新增 `neurflow/hitl.py`，≤150 行）

```python
@dataclass
class PauseRequest:
    request_id: str      # f"{node_id}:{execution_id}" ；审批类追加 nonce: f"{node_id}:{execution_id}:{seq}"
    kind: str            # "node_input" | "tool_approval"
    prompt: str
    options: list[str]           # 前端渲染按钮/分支
    allowed_actions: list[str]   # approve/reject/respond/submit 子集
    timeout_seconds: float       # 0=无限
    paused_at: str               # ISO UTC，懒超时基准
    fallback_action: str | None  # 超时后的动作

class WorkflowPauseSignal(Exception):
    """节点执行器抛出 → 引擎转为挂起（携带 PauseRequest）"""
```

恢复注入：`PauseDecision{request_id, action, value}`；request_id 校验失败 → 409（不静默）。

### 4.3 改动点

1. **引擎**：`_execute_single_node` 捕获 `WorkflowPauseSignal` → instance.status=`suspended`（P1-2 枚举）→ `_save_checkpoint`（含 pending_pause 字段）→ emit `workflow_paused` 事件（新增事件类型）→ 干净退出本层 gather（**第一期收窄：仅普通节点允许暂停，loop/subflow 内抛出视为 failed**，边界写进 docstring）。
2. **human_input 改造**：stub → 抛 `WorkflowPauseSignal`；resume 注入 decision 后按 options 命中分支输出（`branch_<action_id>` 语义对齐 langflow：每个 option 是一个可路由出口）。
3. **approval 改造**：channel 通知保留；`threading.Event` 阻塞删除，改为"发送通知 → 抛 PauseSignal 挂起"；渠道回调（channel 入站消息命中关键词）→ 调 resume API 注入 decision。懒超时：resume 时比对 `paused_at+timeout`，过期 → fallback_action 或 `__expired__` 哨兵（不取任何分支）。
4. **resume API 扩展**（L1073）：body 增加 `{request_id, action, value}`；校验 pending_pause 匹配。
5. **debug 断点不动**：会话内调试语义保留（登记差异：调试是易失会话，HITL 是持久业务挂起——两条链路不同目的，不强行归一）。
6. **env 门控**：`NEUROVA_NEURFLOW_HITL=0`（默认 0）：关闭时 human_input 保持现 timeout 行为、approval 保持现阻塞行为（等价性测试锁定旧路径）；`=1` 启用新契约。前端（CanvasDesignerPage runStatus + 恢复卡片 UI）随 `=1` 另批交付，后端先行。

### 4.4 TDD 用例（新 `test_workflow_hitl.py`）

1. `=1`：human_input 节点 → 执行返回 suspended + SSE 收 `workflow_paused`（含 request_id/options）→ resume 注入 approve → 下游分支收到输出；2. 陈旧 request_id → 409；3. 超时后 resume → 走 fallback / `__expired__` 不取分支；4. approval：channel 回调注入全链（mock channel manager）；5. `=0` 等价性：两节点行为与现状逐字段一致；6. loop 内暂停 → failed（收窄边界）；7. suspended 执行再次 execute（非 resume）→ 拒绝防双跑。

### 4.5 估算与风险

2-3 天（引擎挂起路径是唯一触碰执行主循环的改动——surgical 原则：只在 `_execute_single_node` 捕获点与 execute 收尾处加分支，不动分层/gather/loop 计划逻辑）。风险：暂停时本层还有并发节点在跑——语义定为"本层跑完、下不再进"，即层栅栏挂起（与 langflow process() 层批模型一致）。

---

## 5. P1-3 续跑重授权（Wave 2 小项，净 LOC ≤ 20）

resume 恢复路径校验**发起 resume 的用户 = checkpoint.user_id（或 admin）**——防"他人续跑他人挂起的工作流"。凭据级校验（LLM provider key 有效性、知识库凭据属主）登记 TODO 不本期实现。用例：用户 B resume 用户 A 的 suspended 执行 → 404。

---

## 6. Wave 3 体验项（独立小批）

| 项 | 改动点 | 用例 | 估算 |
|----|--------|------|------|
| **P2-1 版本说明** | `storage._record_version_if_changed`（L483-515）接受 `commit_msg` 参数；API save/publish 透传；前端 WorkflowVersionsDrawer 加输入框 + i18n 11 语言 | 保存带备注 → 版本列表可见；空则仍 "auto snapshot" | 0.5 天 |
| **P2-2 warm start** | publish 时编译 WorkflowDefinition 缓存（fingerprint→deepcopy），execute 热路径命中跳过 `from_dict`；`NEUROVA_NEURFLOW_WARM=1` 默认开，miss 自动回退冷路径 | 同 fingerprint 两次执行输出等价；改图后 fingerprint 变化走冷路径 | 0.5 天 |
| **P2-3 input_schema** | `NodeDefinition` 加可选 `input_schema: JSON Schema`；`workflow_as_tool.py` 透传给 LLM tools；>50 枚举项降级 string（抄 langflow MAX_OPTIONS_FOR_TOOL_ENUM） | 带 schema 工作流的 tool schema 断言；无 schema 行为不变 | 1 天 |
| **P2-4 langfuse tracer** | otel_bridge 挂 langfuse exporter；span 父子先插序坑 langflow 已踩（span_sorting.py），实施时读之 | 登记方案独立评审后另开任务 | 方案 0.5 天 |
| **P2-5 画布切 vue-flow** | 2682 行 CanvasDesignerPage 先拆模块再换渲染层（已装 @vue-flow/* 未用）；对标 langflow useBuildStatus 的节点状态 hook 化 | **单独立项评审**，本方案只立项不排期 | 立项 |

---

## 7. 验收矩阵（DoD）

| 项 | Live-verify | 防回归用例 | 等价性测试 |
|----|-------------|-----------|-----------|
| P0-1 | 真实双用户 curl：A 建的工作流 B 404 | test_workflow_ownership 7 用例 | admin/public 语义回归 |
| P0-2 | kill -9 后 resume 续跑且不重跑 LLM | checkpoint 4 用例 | — |
| P1-2 | 重启后 SSE 从旧游标续播 | recorder 5 用例 | 内存热读路径不变 |
| P1-1 | 前端点暂停→恢复全链路 | hitl 7 用例 | `=0` 门控下旧行为逐字段一致 |
| P1-3 | B resume A 的挂起 → 404 | 1 用例 | — |

**全批次完成判据**：`pytest tests/unit/neurflow tests/unit/collaboration tests/api/neurflow tests/integration/test_neurflow_integration.py -v` 全绿（现有 76+ 文件基线 + 新增 ~24 用例），前端 `npm run test` 全绿；工作树只含本方案文件（并行会话改动不收编）。

## 8. 明确不做（防 scope 蔓延）

Python code 执行组件（沙箱哲学冲突）；AG-UI 全量协议（仅对齐事件词汇命名）；Redis job queue；bundles 拆包；langflow 式 25+ bundles 生态工程。debug 断点并入 HITL 统一（会话语义不同，保留独立）。
