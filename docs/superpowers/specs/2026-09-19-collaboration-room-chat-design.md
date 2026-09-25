# 协作会话群聊（Collaboration Room Chat）设计规格

- 日期：2026-09-19
- 状态：设计已获用户批准（architectural），进入 writing-plans → 实施
- 范围：让 `/collaboration/sessions` 的"打开"从只读详情弹窗升级为**多 Agent 群聊房间**（人可参与）；后端为协作 Project 增加"房间消息"能力。**不改后端既有 console chat 语义**。

## 0. 背景与现状（证据基线）

- 前端 `pages/CollaborationPage.vue` 的"打开"→ `handleViewSession` 仅置 `showDetail=true` 弹一个只读 `a-modal`（描述/状态/成员/创建时间），**不跳任何聊天界面**。
- 后端存在**两套不相干的 session 世界**：
  - **聊天世界**：`sync/session_sync_manager.py`（内存事件总线，`EventType` 含 `USER_MESSAGE/AGENT_REPLY/AGENT_STREAM_CHUNK/SUBAGENT_*/SESSION_*`，多渠道 WS/SSE，历史在内存）+ 持久层 `session_repository.py`(ABC)→`session_manager.py`(文件层，`save_message(agent_id,session_id,role,content,metadata)`)。`/console/chat` 走这套。
  - **协作 Project 世界**：`collaboration/collaboration_isolation.py` 的 `Project`（members/files/workflow/tasks，**无 messages**）；`/collaboration/sessions` 端点由 `manager.list_projects()` 派生，返回 `{id,name,members,owner_id,...}`。
- 已具备且本设计要复用的既有能力：
  - `session_sync_manager` 的会话注册/广播/历史回放/断线 seq gap（`session_sync.py` 端点已暴露 `register_or_create_session`/`create_session`/`get_history`/WS）。
  - `swarm.py` 已把子 Agent 流式事件（`SUBAGENT_CHUNK`）经 `session_sync_manager` 广播进某个 `session_id`——证明"Agent 运行 → 房间事件流"通路存在。
  - 上一轮已建的 `turn_origin`（含 `COLLABORATION`）、`actionability` 门控（LLM 路由设置 opt-in）、群领导选举（`group_leadership`）——本设计的轮次调度直接复用。
  - 成本：`cost_store`/per-turn usage 与 ChatPage 成本环组件。
- 关键约束：`SessionSyncManager` 依 ADR-0008 **故意不实现** `SessionRepository`（纯内存）；故"重开可回看"的持久化必须走 `SessionManager` 文件层。

## 1. 目标 / 非目标 / 验收

目标：进入协作会话 = 进入一个**持久化的多 Agent 群聊房间**；人可发言，@ 某成员 Agent 或默认由群主回应；消息实时流式、按发送者区分；重开可回看历史。

非目标：不改后端 console chat 的 1:1 语义与其端点；不改协作 Project 的既有 CRUD/成员模型（只新增"房间消息"能力）；不引入新前端状态管理库。

验收：见 §8。

## 2. 决策（已与用户敲定）

- 交互模型：**多 Agent 群聊，人可参与**，复用 `session_sync_manager` 事件总线。
- 轮次：**@路由 + 默认群主回应**（复用 turn_origin/actionability/群领导选举）。
- 持久化：**可回看**，`room_id = project_id` 为房间身份。
- 范围：**全功能**（聊天 + 成员管理 + 成本环 + 自动讨论开关 + 跨端同步），但以**垂直切片序列**交付降险。
- 持久层落点（本设计定稿）：**复用 `SessionManager`（`get_session_repository()`）**，以 `agent_id = session_id = room_id` 存房间消息，消息 `metadata.{sender_type, sender_id}` 承载归属，`role ∈ {user, assistant}`。理由：零新表、零 schema 改动、避免为多发送者去扭曲 console chat 的 1:1 存储；文件层天然持久可回看。

## 3. 架构与组件（三个单一职责单元 + 前端）

- `RoomStore`（持久，薄封装 `SessionRepository`）：
  - `append(room_id, sender_type, sender_id, content, meta) -> msg`
  - `history(room_id, limit) -> List[{sender_type,sender_id,role,content,ts,meta}]`
  - 内部：`save_message(agent_id=room_id, session_id=room_id, role=user|assistant, content, metadata={sender_type,sender_id,**meta})`；读回时从 metadata 还原归属。
- `RoomBus`（实时，薄封装 `session_sync_manager`）：
  - `ensure_room(room_id, meta)` → `register_or_create_session(session_id=room_id, metadata={members,owner})`
  - `publish(room_id, event_type, payload)` → `SessionEvent(...)` 广播给所有连接端。
- `RoomTurnRouter`（调度，纯逻辑 + 编排）：
  - 输入：一条人类消息（room_id, text, actor_user）+ 房间成员/群主配置。
  - 解析 @提及 → 目标 agent 集（被 @ 者；无 @ → 群主）。
  - 门控：对每个目标跑 `actionability`（opt-in，默认放行）+ 群领导（自动应答者唯一化，opt-in）。
  - 执行：对通过的目标 Agent 调 `Agent.chat(text, session_id=room_id, metadata={turn_origin:'collaboration', ...})`，流式 chunk → `RoomBus.publish(AGENT_STREAM_CHUNK)`；完成 → `RoomStore.append(assistant)` + `RoomBus.publish(AGENT_REPLY)`。
- 前端 `CollaborationRoomPage`：拉历史（RoomStore 端点）→ 订阅实时流（复用 session-sync WS/SSE 客户端）→ 发消息（POST 房间端点）→ 按 sender 分组气泡 + 成本环 + 成员/自动讨论控件。

## 4. 数据流（一条人类消息）

1. 前端 POST `/collaboration/rooms/{room_id}/messages {text}`（携带登录态）。
2. 后端：`RoomStore.append(user)` 落库 → `RoomBus.publish(USER_MESSAGE)` 广播（含 actor）。
3. `RoomTurnRouter` 解析 @/群主 → 选定回应 Agent → 异步跑 `Agent.chat`（流式）。
4. 每个 chunk → `RoomBus.publish(AGENT_STREAM_CHUNK, {sender_id})`；结束 → `RoomStore.append(assistant)` + `RoomBus.publish(AGENT_REPLY)`。
5. 所有连到该 room 的端（多浏览器/设备）实时收到。

## 5. 后端端点（新增文件 `api/endpoints/collaboration_room_api.py`，不并入已 1000+ 行的 `collaboration_api.py`）

- `GET  /collaboration/rooms/{room_id}` → 房间元信息（成员、群主、状态）。
- `GET  /collaboration/rooms/{room_id}/messages?limit=` → 历史（RoomStore.history）。
- `POST /collaboration/rooms/{room_id}/messages {text}` → 落库 + 广播 + 触发轮次（§4）。
- 实时订阅：复用既有 `session_sync.py` 的 WS/SSE（`session_id=room_id`），不新增传输端点。
- 鉴权：`get_current_user`；仅 Project 成员可读写其房间。

## 6. 轮次与调度细则

- @路由：解析 `@<agent_name>` → 匹配成员；命中则仅其回应；未命中/无 @ → **默认应答者**。
- **默认应答者定义**：房间配置 `responder_agent_id`（一个成员 Agent）；未配置则取 `Project.members` 中首个 Agent。注意 `owner_id` 是人类创建者、**不是**应答 Agent，二者不可混淆。
- 复用既有门控：`turn_origin='collaboration'`；`actionability`（默认关，opt-in）；`group_leadership`（opt-in，保证同一时刻唯一自动应答者）。
- 自动讨论开关（全功能项）：开启时由 coordinator 依 `agent/team.py::orchestrate` 或 swarm 派生驱动多轮，直到收敛或触达**轮次上限/预算帽**（复用 swarm fan-out 治理：`MAX_ACTIVE_CHILDREN`、预算闸、模型冷却）。默认关。
- 失败：目标 Agent 未注册/异常 → `RoomBus.publish(AGENT_ERROR)` + 落一条系统提示；不静默。

## 7. 错误处理与边界

- 落库与广播解耦：广播优先（实时体验），`RoomStore.append` 失败记 error 日志、不回滚广播（避免持久层抖动打断聊天）。
- 断线重连：`get_history` 回放 + seq gap 探测（session_sync_manager 既有）。
- 空成员/无群主：房间只读展示 + 提示"未配置应答者"。
- 幂等：消息 `message_id` 由前端生成（client_timestamp）以便乐观渲染与去重回放。

## 8. 验收标准

1. `/collaboration/sessions` 点"打开"→ 进入 `/collaboration/sessions/:roomId` 群聊界面（不再只是详情弹窗）。
2. 人发消息 → 被 @ 的成员 Agent 流式回应；无 @ → 群主回应；气泡按发送者区分（名字/头像）。
3. 刷新/重开该房间 → 历史消息完整回看（持久化生效）。
4. 两个浏览器标签打开同一房间 → 一端发消息另一端实时收到（复用 session_sync 广播）。
5. 成本环显示本轮 token/成本；成员管理、自动讨论开关可用。
6. `npm run build`（vue-tsc）0 错误；后端受影响 pytest 套件 0 失败；关键路径有单测。

## 9. 测试策略（TDD，垂直切片）

- 后端单测：`RoomStore`（append/history、sender 归属经 metadata 往返、room 隔离）；`RoomTurnRouter`（@解析、无@回落群主、门控跳过、失败发 AGENT_ERROR——mock Agent.chat 与 RoomBus/RoomStore）；端点（POST→落库+广播+触发轮次；GET 历史；鉴权）。
- 前端：`CollaborationRoomPage`（拉历史/发消息/按 sender 渲染/成本环）vitest；"打开"跳路由断言；路由解析。
- 实机：起服务，真实房间人发→成员 Agent 流式回应→刷新回看→双标签同步。

## 10. 实施切片（sequenced，供 writing-plans 拆票）

1. **持久与只读**：`RoomStore` + `GET /rooms/{id}` + `GET /rooms/{id}/messages`；前端房间页拉历史只读渲染（示踪弹）。
2. **实时能聊**：`POST /rooms/{id}/messages` + `RoomBus` 接 session_sync + `RoomTurnRouter`（@路由+群主）接 `Agent.chat` 流式；前端发消息 + 订阅流 + 乐观渲染。
3. **入口切换**：sessions"打开"改跳房间路由；（详情弹窗降为概览或移除）。
4. **成员管理 + 成本环**：房间页头控件；per-turn usage 接线。
5. **自动讨论开关**：coordinator/蜂群多轮 + fan-out 治理帽 + actionability/群领导 opt-in 接线。

## 11. 涉及文件

后端：`neurova/collaboration/room_store.py`(新)、`room_bus.py`(新)、`room_turn_router.py`(新)、`api/endpoints/collaboration_room_api.py`(新)、路由注册 `api/app.py`/`endpoints/__init__.py`；复用 `session_manager.py`、`sync/session_sync_manager.py`、`agent/swarm.py`、`agent/team.py`、`agent/turn_origin.py`、`agent/actionability.py`、`channels/group_leadership.py`、`cost_store`。
前端：`pages/CollaborationRoomPage.vue`(新)、`router/index.ts`、`api/modules/collaboration.ts`、`stores/collaboration.ts`、`pages/CollaborationPage.vue`（打开改跳）、复用 session-sync 客户端/消息气泡/成本环组件、`i18n/locales/{zh-CN,en-US}.ts`。

## 12. 风险与回退

- 纯增量：新增房间层，不改 console chat 既有端点/存储语义 → 回退=摘除房间路由与端点。
- 持久复用 SessionManager 以 room_id 作 agent_id 键：需确认不与真实 agent 会话命名冲突（room_id=project_id 前缀 `project_`，天然不撞）。
- 多 Agent 并发回应成本：默认 @路由/群主单一回应；自动讨论受 fan-out 治理帽约束。
- 全功能范围大：以 §10 切片序列交付，每片独立可回滚、先红后绿。
