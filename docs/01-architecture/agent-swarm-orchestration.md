# Agent 蜂群编排能力 — 实施文档

## 概述

主 Agent 具备**蜂群能力**（ZCode 式）：对话中通过工具动态派生子 Agent（可并行/后台），
子 Agent 对话在聊天页以可最小化的小窗实时展示（逐 token 流式）；输出**双通道回流**
（直传报告 + 上下文池归档）。画布工作流复用同一执行核心（静态编排形态），
支持 condition 真分支、分层并行、**Loop 真循环**、ComfyUI 节点执行、ACP 消息协议。

---

## 1. 蜂群核心（主 Agent 动态编排）

### SwarmManager — `neurova/agent/swarm.py`

```python
from neurova.agent.swarm import get_swarm_manager

swarm = get_swarm_manager()
result = await swarm.spawn(
    task="子任务描述",           # 必需，自包含（子 Agent 看不到主对话历史）
    agent_id="researcher",       # 可选；不存在回退 default
    session_id="sess-xxx",       # 可选；事件广播目标（聊天页小窗）
    background=False,            # True 立即返回 subagent_id
    origin="chat",               # chat | workflow
    stream=True,                 # 逐 token 广播 SUBAGENT_CHUNK
    initiator_agent=main_agent,  # 报告归档进其上下文池
)
```

- 子 Agent 解析：`get_agent_instance(agent_id)`（`app_state["agents"]` 注册中心），
  每个子 Agent 有独立人设/记忆/模型；不存在回退 default 并标注 `resolved_agent_id`
- 事件广播：`SUBAGENT_STARTED` / `SUBAGENT_CHUNK` / `SUBAGENT_COMPLETED`
  （`session_sync_manager.EventType` 新增），payload 含 subagent_id/agent_name/task/report
- 双通道回流：
  - 直传：报告在 spawn 返回值中（工具结果 → 主 Agent）
  - 池归档：`[子Agent报告] ...` 以 EXPERIENCE 源入发起者上下文池（活水，按需召回）

### 三个新内置工具（`builtin_tools.py` schema + `tool_executor.py` 分支）

| 工具 | 参数 | 说明 |
|---|---|---|
| `spawn_subagent` | task, agent_id?, background? | 蜂群派生；一条回复多次调用 = 并行蜂群 |
| `subagent_status` | subagent_id | 查询后台子 Agent 状态/报告 |
| `list_agents` | - | 列出可用子 Agent（id/name/description/model） |

session_id 透传链：`ChatPipeline._init_agent_state` 存 `agent._current_session_id` →
工具读取。`event_emitter` 经 metadata 透传（`_init_agent_state` 提取）。

---

## 2. 子 Agent 逐 token 流式

- `ChatContext.event_emitter`：流式路径每收到 content/reasoning chunk 时回调
  （`_call_loop_stream`），不影响聚合返回
- SwarmManager 构造 emitter → 每 chunk 广播 `SUBAGENT_CHUNK`
  （create_task 调度，不阻塞生成循环）

---

## 3. 引擎增强（`execution_engine.py` + `dag.py` + `safe_eval.py`）

### condition 真分支
- exec_condition 求值后 branch（true/false）写入 output
- 引擎按**边活跃性不动点传播**：节点被跳过 ⇔ 所有（非回边）入边不活跃；
  边不活跃 ⇔ 未命中分支，或 source 已跳过。汇聚点自然保护。

### 分层并行
- Kahn 分层，层内 `asyncio.gather` 并发；parallel 节点多分支天然同层
- 层内失败 → 工作流失败（`_NodeExecutionError`）

### Loop 真循环（重点）
- **DAG 回边豁免**：`target_handle == "loop_body"` 的边不参与判环/拓扑排序
  （`dag.is_loop_back_edge`）；其余环仍拒绝
- **引擎迭代驱动**（`_run_loop`）：
  - body 入口 = loop 经 `current` 出边的目标；出口 = 回边源
  - 每轮：loop 的 output = 当前迭代值（body 用 `${loop_id.output}` 引用）→
    拓扑序执行 body → 求值 `break_condition`（安全 DSL，上下文
    `$iteration/$current/$node/$var/$input`）→ 满足或达 max_iterations（≤1000）退出
  - `loop_done` 输出 `{iterations, last_output, broken}`；body 节点标记 loop_driven
    防主循环重复执行；嵌套 loop 递归驱动（内层优先规划）

### 安全条件求值 — `safe_eval.py`
无 eval/exec 的递归下降解析器（比较/and/or/not/in、len/str/int/float/bool 白名单、
$变量查找），失败一律 False。`exec_condition` 与 loop break_condition 共用。

---

## 4. ComfyUI 集成（照 tests/unit/collaboration/ RED 契约实现）

| 模块 | 职责 |
|---|---|
| `comfyui_client.py` | HTTP 客户端（单例；`NEUROVA_COMFYUI_HOST` 配置；POST {host}/prompt；异常隔离为 failed） |
| `comfyui_nodes.py` | 12 个核心节点注册到 NodeRegistry（`comfyui:{class_type}`，含端口/sub_blocks/执行器） |
| `comfyui_importer.py` | ComfyUI API JSON → WorkflowDefinition（标量→config、数组→边、网格布局、metadata 保留原始 JSON） |
| `neurflow_api.py` | `POST /comfyui/import`、`GET /comfyui/status`、`POST /comfyui/execute` |
| `adapters.sync_all` | 挂 comfyui 注册钩子（失败不阻断） |

---

## 5. ACP 消息协议接线

- `agent_adapter.py`（新）：Agent 实例 → ACP handler（TASK_ASSIGNMENT → agent.chat →
  TASK_RESULT，correlation_id 关联）；`register_runtime_agents()` 批量注册
- `acp_api.py`（新，挂载于 `/api/acp`）：`GET /agents`、`POST /agents/register`、
  `POST /send`、`POST /request`（请求-响应）、`POST /teams/orchestrate`
  （AgentTeam 多角色步骤编排，请求携带 members: [{agent_id, role}]）

---

## 6. 画布桥接

- `collaboration/canvas_bridge.py`：画布快照 → WorkflowDefinition
  （边 `{source:{nodeId,portId}}` → `{source, source_handle: portId}`；
  未知节点类型 ValueError 列明；旧纯坐标边跳过）
- `POST /collaboration/canvas/{id}/run`：转换 → 后台执行引擎（可传 session_id 联动聊天小窗）
  → 立即返回 runId；`GET /canvas/{id}/runs/{run_id}` 查询节点级状态

---

## 7. 前端

### CanvasDesignerPage
- **agent 节点专用面板**：Agent 下拉（agentStore.agentOptions）+ task 文本域
- **执行状态可视化**：节点着色（running 黄/success 绿/failed 红/skipped 灰）+
  1s 轮询 + 属性面板查看节点输出
- **动态节点库**：palette 从 `/neurflow/nodes` 拉取（含端口/sub_blocks），
  静态库 fallback；comfyui/tool/skill/mcp 节点自动出现

### 聊天页子 Agent 小窗
- `useSessionSync.ts`：WS `/api/v1/sync/ws/{session_id}?channel_type=web-chat-{tabId}`
  （标签页唯一渠道防互顶），指数退避重连，sessionId 变化自动重连
- `SubAgentPanel.vue`：浮动小窗（右下堆叠），任务+流式正文（打字光标），
  最小化折叠为标题条/恢复/关闭；状态色边框
- ChatPage 订阅事件驱动小窗增删改

---

## 8. 测试清单（全绿）

| 文件 | 数量 | 覆盖 |
|---|---|---|
| `tests/unit/agent/test_swarm_manager.py` | 12 | spawn 前台/后台/回退/故障隔离/事件/池归档 |
| `tests/unit/agent/test_swarm_tools.py` | 8 | 三工具 schema 与执行分支 |
| `tests/unit/agent/test_chat_stream_events.py` | 6 | emitter 转发/session 透传 |
| `tests/unit/neurflow/test_loop_execution.py` | 7 | 回边豁免/迭代/跳出/last_output/防重复 |
| `tests/unit/neurflow/test_condition_branching.py` | 5 | 真分支/跳过/汇聚点/输入上下文 |
| `tests/unit/neurflow/test_parallel_execution.py` | 2 | 层内并发计时/失败传播 |
| `tests/unit/neurflow/test_canvas_bridge.py` | 6 | 转换/端口映射/未知类型/坐标边跳过 |
| ComfyUI 契约（5 文件）+ ACP 协议（既有） | 42+35 | 照 RED 契约全绿 |

已知既有失败（与本次无关）：test_neurloop_medium_fixes 的 Context/Emotion 节点 4 例
（stash 验证为改动前已存在）。
