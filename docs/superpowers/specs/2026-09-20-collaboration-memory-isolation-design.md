# 协作群聊记忆的会话作用域隔离 —— 设计

## 0. 背景与问题
协作群聊（房间）与普通单聊共用同一 agent 的**长期记忆层**。记忆的隔离三元组是
`(agent_id, neuser_id, user_id)`（`memory_layer/manager.py` 三层过滤、`mem_core.py:131`
SQL 注入），**不含会话维度**。因此：

- 群聊每轮经 `Agent.chat` → `post_chat_pipeline._step_save_memory` 写入的记忆，会被
  单聊、以及其它群召回 → 串味 / 污染正常单聊。
- 反向：群聊 agent 会召回用户单聊里的记忆（把私聊内容说进群）。
- 群与群之间记忆互通 → 混淆。

同时短期上下文已按 `(agent_id, session_id=room_id)` 天然隔离（`chat_pipeline.py:650-665`），
群↔群、群↔单的**会话文件层**不串；污染只发生在跨会话共享的长期记忆层。

## 1. 目标（决策已定档）
- 采用**按会话打标 + 检索过滤**（方案 3）。
- 可见性规则（方案 2）：
  - 单聊轮：仅召回 `direct`（群聊记忆绝不泄入单聊）。
  - 群 R 轮：召回 `direct` + `room:R`（读单聊基线更懂你；其它群互不可见）。
  - 群↔群彻底隔离；单聊不被任何群污染。

## 2. 作用域模型（零 schema 迁移）
- 记忆的 `metadata` 是 JSON 列、随 `to_dict()` 完整往返（`models.py:447`），已存
  `session_id`。新增 `metadata["chat_scope"]`：
  - `direct`：普通/单聊（缺省即视为 direct，兼容全部历史记忆）。
  - `room:<room_id>`：协作群聊（room_id = 协作 project id，`project_` 前缀、全局唯一）。
- 不引入新表列、不做 DB 迁移：靠 metadata + 读侧过滤达成隔离。

## 3. 写入侧（打标）
- `RoomTurnRouter` 调 `agent.chat` 时 metadata 带 `turn_origin="collaboration"`、
  `session_id=room_id`（已有）。
- `post_chat_pipeline._step_save_memory` 读取本轮 metadata：`turn_origin=="collaboration"`
  时给两条记忆（用户句 / 助手句）写 `chat_scope="room:<room_id>"`；否则 `direct`。
- 单聊 / 渠道等非协作路径行为不变（打 `direct`，语义等同历史）。

## 4. 检索侧（过滤，单点闸口）
- 唯一必由出口：`chat_pipeline._retrieve_memories` 末尾 `ctx.relevant_memories = result.memories`。
- 在此按当前轮 `turn_origin` / `session_id` 计算允许 scope 集，对 `result.memories`
  做 post-filter（纯函数 `memory_scope.filter_memories_by_scope`）：
  - 单聊轮 allowed=`{direct}`；群轮 allowed=`{direct, room:<room_id>}`。
  - 记忆 scope 取 `metadata.chat_scope`，缺省 `direct`。
- post-filter 兜底于**注入上下文前**，无论哪个召回引擎遗漏都不外泄（防御纵深）。
- 结晶经验 / 上下文池等旁路召回按 `session_id` 独立分池，天然按房间隔离，本期不改。

## 5. 群会话不混入单聊列表
- 群轮 `save_memory=True` 会在 `(agent, room_id)` 另存会话文件，可能出现在单聊侧栏。
- 控制台单聊会话列表端点过滤掉协作房间会话（`turn_origin=collaboration` / `project_` 前缀），
  群记录只在协作房间页按 room_id 读取（RoomStore）。

## 6. 测试（TDD）
- 纯函数：`scope_tag_for_turn` / `allowed_scopes_for_turn` / `filter_memories_by_scope`
  三向断言（群A召不到群B、单聊召不到群、群召得到单聊基线；缺省标签=direct）。
- `_step_save_memory`：collab 轮写入 metadata 带 `room:<id>`，非 collab 带 `direct`。
- `chat_pipeline._retrieve_memories`：collab 与非 collab 上下文分别只保留允许 scope。
- 实机：两个群 + 一次单聊各埋独有事实，交叉验证仅按规则可见；单聊不出现群内容。

## 7. 回归与边界
- 默认 direct + 读侧唯一闸口，把 blast radius 压到最小；单聊既有记忆无需迁移。
- 依赖 room_id 全局唯一（project_ 前缀）与 `turn_origin` 标记；不引入第三方依赖。
- 记忆写入仍 `save_memory=True`（保留打标），仅新增 chat_scope 字段。

## 8. 落地补充（本轮追加解决的三项）
1. **历史遗留泄漏**：`memory_scope.scope_from_metadata` 在无 `chat_scope` 时从
   `metadata.session_id` 的 `project_` 前缀回溯判定为 `room:<id>`，使打标启用前的群聊
   记忆归回其房间，不再被当 direct 泄入单聊/他群（零迁移，单聊跨会话召回不受影响）。
2. **房间轮空转（根因在错误掩盖）**：`agent/loops/base.py` ToolRouter fallback 处，
   旧写法 `router_result.error if router_result else "执行返回空"` 因 `ToolResult.__bool__`
   即 success，失败结果为假值 → 真实 error 被抹平为笼统文案，模型无从纠错而反复重试、
   迟迟不出正文。改为忠实透出 `router_result.error`。迭代上限/停滞检测已存在（`_max_tool_rounds`、
   `IterationGate`、`_assess_stagnation`），非缺上限。
3. **旁路召回**：`context/orchestrator.build_context` 新增 `chat_collab`/`chat_room_id`，
   对 `context_pool.draw()` 的"历史回忆"按同一 `filter_by_scope` 过滤（chunk 归属由其
   metadata.session_id 的 project_ 前缀判定）。单聊/非协作仅见 direct（仍跨普通会话召回），
   排除任何房间归档；群轮见 direct + 本群。结晶/EKB 为 agent 级泛化模式（非逐字私聊），
   且上下文池按 session 分区，本期不额外纳入。
