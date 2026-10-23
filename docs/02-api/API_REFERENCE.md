# Neurova API 接口文档

> **版本**: v1.0.0-beta1 | **基础路径**: `/api/v1` | **协议**: HTTP/HTTPS | **数据格式**: JSON  
> **最后更新**: 2026-06-07 | **端点模块**: 75 个 | **端点总数**: 625+

## 通用说明

**响应格式**: `{"code": 0, "data": {}, "message": "success", "request_id": "uuid"}`

**认证**: `Authorization: Bearer <token>` (JWT Token, 部分端点支持 API Key)

**分页**: `limit` (默认50), `offset` (默认0)

---

## 一、核心功能 (15模块)

### 1. `/api/v1/health` — `health.py` | 无认证
- `GET` 系统健康检查

### 2. `/api/v1/` — `home.py` | 无认证
- `GET` 首页概览

### 3. `/api/v1/chat` — `chat.py` | 无认证
- `POST` 发送消息 | `POST /stream` 流式SSE | `GET /history` 对话历史

### 4. `/api/v1/agents` — `agent.py` | 无认证
- CRUD: `GET` 列表 | `GET /{id}` 详情 | `POST` 创建 | `DELETE /{id}` 删除
- 扩展: `GET /{id}/stats` 统计 | `POST /{id}/switch` 切换 | `GET/PUT /{id}/constitution` 宪法 | `GET/PUT /{id}/personality` 性格 | `POST /{id}/decision` 决策

### 5. `/api/v1/auth` — `auth.py` | 部分认证
- `POST /login` 登录 | `POST /refresh` 刷新Token | `GET /me` 当前用户(需认证) | `POST /register` 注册 | `POST /register/send-code` 发验证码 | `POST /register/verify-code` 验证 | `POST /register/invite` 邀请注册

### 6. `/api/v1/memory` — `memory.py` + `memory/` | 子模块需认证
- **主CRUD**: `GET` 列表 | `GET /{id}` 详情 | `POST` 创建 | `PUT /{id}` 更新 | `DELETE /{id}` 删除 | `POST /search` 搜索 | `GET /stats` 统计
- **子模块** (均需认证):
  - `working_memory.py` -> `GET/POST /working` 工作记忆
  - `emotion.py` -> `GET /emotion` | `POST /emotion/analyze` | `GET /emotion/stats`
  - `reflection.py` -> `GET /reflection` | `POST /reflection/trigger`
  - `profile.py` -> `GET/PUT /profile`
  - `metacognition.py` -> `GET /metacognition/monitor` | `POST /metacognition/reflect` | `POST /metacognition/optimize` | `GET /metacognition/health`
  - `questions.py` -> `GET/POST /questions` | `POST /questions/{qid}/answer`
  - `tkg.py` -> `GET/POST /tkg/facts` | `GET /tkg/conflicts`
  - `eki.py` -> `GET /eki` | `POST /eki/optimize`

### 7. `/api/v1/models` — `model.py` | 无认证
- CRUD + `POST /probe-multimodal` | `POST /check-connection`

### 8. `/api/v1/providers` — `provider.py` | 无认证
- CRUD + `POST /activate-model` | `GET /active-model` | `GET /{id}/models/discover` | `POST /{id}/models/{m}/probe-multimodal` | `POST /{id}/check-connection` | `POST /{id}/models/{m}/check-connection`

### 9. `/api/v1/skills` — `skill.py` | 无认证
- `GET` 列表 | `GET /{id}` 详情 | `POST /{id}/execute` 执行 | `GET /stats` 统计 | `POST /learn` 学习 | `GET /tips` 提示

### 10. `/api/v1/settings` — `settings.py` | 需认证（写面另加管理员门）
- `GET/PUT` 系统设置 | `GET/PUT /llm` LLM配置 | `POST /llm/test` 测试
- 「某个用户默认看什么语言」**不在这一面**（§6-167 退役）：`general.language` 与平铺 `language` 两个键都已摘掉，写它们回 **400 并给出去处**，读它们回 **404**；起点改由 `/api/v1/language/preferences/default`（写面仅管理员）承载
- 实测（活体 `tests/manual/languageFace_outOfBox_batch167.py` 第 [31]/[32]/[33] 项）：无凭证 `GET /settings` 与 `GET /settings/{key}` 都是 **401**，带凭证读一个不存在的键是 **404**——本行原先写的是「无认证」，与本批动过的那个面不符，按读数改；**附录里其余模块的「无需认证」整表仍未逐模块复核**（§6-158 留的那笔账一寸没变）

### 11. `/api/v1/logs` — `logs.py` | 无认证
- `GET` 系统日志 (level, limit, start_time, end_time)

### 12. `/api/v1/stats` — `stats.py` | 无认证
- `GET` 总览 | `GET /agents` | `GET /memories` | `GET /skills`

### 13. `/api/v1/monitor` — `monitor.py` | 无认证
- `GET` 监控 | `GET /performance` | `GET /resources`

### 14. `/api/v1/scheduler` — `scheduler.py` | 无认证
- `GET/POST /tasks` | `PUT/DELETE /tasks/{id}` | `POST /tasks/{id}/toggle`

### 15. `/api/v1/trace` — `trace.py` | 无认证
- `GET` 轨迹 | `GET /{id}` 详情 | `GET /agent/{agent_id}`

---

## 二、生成与知识 (8模块)

### 16. `/api/v1/generation` — `generation.py`
- `POST /text` | `POST /image` | `POST /video` | `POST /audio` | `GET /tasks/{id}`

### 17. `/api/v1/image` — `image.py`
- `POST /analyze` | `POST /edit` | `POST /convert`

### 18. `/api/v1/media` — `media.py`
- 写：`POST /save`（表单字段 `media_type` 必填；无 `POST /upload`）｜ `POST /batch-delete`（body `{media_ids, mode}`）｜ `PUT /config` ｜ `POST /cache/clear`
- 读：`GET /list`（`agent_id`/`media_type`/`search`/`offset`/`limit`）｜ `GET /config` ｜ `GET /{media_id}`（内容）｜ `GET /{media_id}/metadata` ｜ `GET /download/{media_id}` ｜ `GET /stats/{agent_id}` ｜ `GET /memory/{memory_id}` ｜ `GET /storage-path/{media_type}`
- 回收站（§6-158）：`DELETE /{media_id}?mode=trash` 软删 ｜ `GET /trash` 读面 ｜ `POST /{media_id}/restore` 恢复 ｜ `DELETE /{media_id}?mode=permanent` 彻底删除。**缺省档是 `permanent`**——列表里那个删除按钮至今仍是硬删
- 认证：路由级 `Depends(get_current_user)`，**无凭证即 401**（实测于 §6-158 的活体第 [8] 项，附录那张表的旧值见其脚注）
- 字面段（`/trash`、`/list`、`/config`、`/batch-delete`…）必须注册在 `GET /{media_id}` 之前，守卫见 `tests/unit/api/test_media_route_order_guard.py`

### 19. `/api/v1/knowledge` — `knowledge.py`
- CRUD: `GET` | `POST` | `GET/PUT/DELETE /{id}` | `POST /search`

### 20. `/api/v1/growth` — `growth.py`
- `GET /logs` | `GET /reports` | `GET /metrics` | `POST /events`

### 21. `/api/v1/sleep` — `sleep.py`
- `GET/POST /config` | `GET /status` | `POST /trigger` | `GET /dreams`

### 22. `/api/v1/runtime` — `runtime.py`
- `GET` 列表 | `GET /{id}` | `POST /execute` | `GET /results/{id}`

### 23. `/api/v1/marketplace` — `marketplace.py`
- `GET` 列表 | `GET /{id}` | `POST /publish` | `POST /install/{id}`

---

## 三、渠道与通知 (7模块)

### 24. `/api/v1/channels` — `channel.py`
- CRUD + `POST /{id}/toggle`

### 25. `/api/v1/channel-adapters` — `channels.py`
- CRUD

### 26. `/api/v1/channel-configs` — `channel_config.py`
- CRUD

### 27. `/api/v1/channel-sharing` — `channel_sharing.py`
- CRUD

### 28. `/api/v1/notifications` — `notifications.py`
- `GET` | `POST /{id}/read` | `POST /read-all` | `DELETE /{id}`

### 29. `/api/v1/audit` — `audit.py`
- `GET` | `GET /stats` | `GET /export`

### 30. `/api/v1/firewall` — `firewall.py`
- `GET/POST /rules` | `PUT/DELETE /rules/{id}` | `GET /status`

---

## 四、协作与团队 (7模块)

### 31. `/api/v1/analytics` — `analytics.py`
- `GET` | `GET /users` | `GET /agents` | `GET /conversations`

### 32. `/api/v1/collaboration` — `collaboration_api.py`
- tasks CRUD | workflows | team | discussions | records

### 33. `/api/v1/groups` — `groups_api.py`
- CRUD + members

### 34. `/api/v1/teams` — `teams_api.py`
- CRUD + members

### 35. `/api/v1/workflows` — `workflows_api.py`
- CRUD + execute + executions

### 36. `/api/v1/tasks` — `tasks_api.py`
- CRUD + status

### 37. `/api/v1/projects` — `projects_api.py`
- CRUD

---

## 五、工具与技能 (12模块)

### 38. `/api/v1/rules` — `rules_api.py`
- CRUD

### 39. `/api/v1/webhooks` — `webhooks.py`
- CRUD + test

### 40. `/api/v1/enhanced-users` — `enhanced_users_api.py`
- CRUD

### 41. `/api/v1/user-groups` — `user_group_api.py`
- CRUD

### 42. `/api/v1/files` — `files_api.py`
- `POST /upload` | `GET` | `GET /{id}` | `DELETE /{id}` | `GET /{id}/download`

### 43. `/api/v1/file-flows` — `file_flows_api.py`
- CRUD + process

### 44. `/api/v1/tools` — `tool_schema.py`
- `GET` | `GET /{id}` | `POST /{id}/validate`

### 45. `/api/v1/tool-layers` — `tool_layers.py`
- `GET` | `GET /{id}` | `POST /{id}/activate`

### 46. `/api/v1/skill-pool` — `skill_pool_api.py`
- `GET` | `POST` | `DELETE /{id}` | `POST /{id}/enable` | `POST /{id}/disable`

### 47. `/api/v1/marketplace` — `marketplace.py`
- `GET /skills` | `GET /skills/{id}` | `POST /skills/{id}/install` | `DELETE /skills/{id}/install` | `GET /installed`

### 48. `/api/v1/skill-versions` — `skill_version_api.py`
- `GET` | `GET /{id}` | `POST /{id}/rollback`

### 49. `/api/v1/mobile` — `mobile_pairing.py` | 需认证
- `POST /pairing/generate` | `GET /pairing/qrcode/{code}` | `POST /pairing/confirm` | `GET /pairing/status/{code}` | `GET /pairing/list` | `DELETE /pairing/{id}` | `WS /ws`
- `WS /ws?code=…`（或 `?token=…`）的消息面：入站 `ping` / `chat:send` / `chat:cancel` / `agent:switch` / `session:list` / `session:create`；出站 `pong`、`chat:chunk`→`chat:done`、`agent:switched`、`session:*`，失败一律回 `type=error` 带 `code`。
- §6-154（批 17）改到实况的两点：**`chat:send` 此前从未真的跑起来**——调用点按 `content=`/`user_id=` 传参，与 `Agent.chat_stream`/`Agent.chat` 的真签名（`user_input=`/`metadata=`）对不上 ⇒ 必 `TypeError`，又被一条不记日志的 catch-all 转成 `chat_failed`，服务端零痕迹。现在形状接对、回合内建立请求级属主（usage 入账、按日配额、会话归属同 §6-153 的边界口径），并把"取不到 Agent"的两种因由分开回：`agent_not_found`（确实没有）与 `agent_lookup_failed`（查询自己抛了，日志留服务端）。

---

## 六、记忆增强 (7模块)

### 50. `/api/v1/experience` — `experience_knowledge_api.py`
- `GET` | `POST` | `GET /{id}` | `POST /search` | `GET /stats`

### 51. `/api/v1/knowledge-graph` — `knowledge_graph_api.py`
- `GET/POST /nodes` | `GET/POST /edges` | `GET /query` | `GET /visualize`

### 52. `/api/v1/knowledge-integration` — `knowledge_integration.py`
- `POST /sync` | `GET /status` | `GET /sources` | `POST /sources`

### 53. `/api/v1/semantic-search` — `semantic_search_api.py`
- `POST /search` | `GET /suggestions` | `POST /index` | `GET /index/status`

### 54. `/api/v1/enhanced-memory-search` — `enhanced_memory_search_api.py`
- `POST /search` | `POST /search/multi` | `GET /filters` | `POST /reindex`

### 55. `/api/v1/memory-timeline` — `memory_timeline_api.py`
- `GET /timeline` | `GET /timeline/{memory_id}` | `GET /stats`

### 56. `/api/v1/synonyms` — `synonym_api.py`
- `GET` | `POST` | `PUT /{id}` | `DELETE /{id}` | `POST /expand`

---

## 七、扩展功能 (12模块)

### 57. `/api/v1/benchmark` — `benchmark.py`
- `GET /suites` | `POST /run` | `GET /results/{id}` | `GET /history`

### 58. `/api/v1/console` — `console.py`
- `GET /dashboard` | `GET /system` | `POST /command`

### 59. `/api/v1/plugins` — `plugin.py`
- `GET` | `POST` | `GET /{id}` | `DELETE /{id}` | `POST /{id}/enable` | `POST /{id}/disable`

### 60. `/api/v1/sandbox` — `sandbox.py`
- `POST /create` | `GET /{id}` | `POST /{id}/execute` | `DELETE /{id}`

### 61. `/api/v1/builder` — `builder.py`
- `POST /build` | `GET /status/{id}` | `GET /history`

### 62. `/api/v1/computer` — `computer.py`
- `POST /screenshot` | `POST /click` | `POST /type` | `POST /navigate` | `GET /snapshot`

### 63. `/api/v1/shared-config` — `shared_config.py`
- `GET` | `PUT` | `GET /history`

### 64. `/api/v1/openplatform` — `openplatform_keys.py`
- `GET/POST /keys` | `DELETE /keys/{id}` | `POST /keys/{id}/rotate`

### 65. `/api/v1/model-adapter` — `model_adapter.py`
- CRUD

### 66. `/api/v1/context` — `context.py` | 需认证
- CRUD + `POST /{id}/compress` | `GET /{id}/tokens`

### 67. `/api/v1/context-pool` — `context_pool_settings.py` | 需认证
- `GET/PUT /settings` | `GET/POST /pools` | `DELETE /pools/{id}` | `GET /stats`

### 68. `/api/v1/metacognition` — `metacognition_api.py` | 需认证
- `GET` | `POST /evaluate` | `GET /insights` | `POST /reflect` | `GET /history` | `PUT /config`

---

## 八、其他模块 (8模块)

### 69. `/api/v1/agent-enhancement` — `agent_enhancement.py` | 需认证
- `GET` | `POST /apply` | `GET /{agent_id}` | `DELETE /{agent_id}/{enhancement_id}` | `GET /available`

### 70. `/api/v1/agent-communication` — `agent_communication_api.py` | API Key认证
- `POST /message` | `GET /messages` | `GET /channels` | `POST /broadcast` | `GET /status`

### 71. `/api/v1/logs-api` — `logs_api.py` | 需认证
- `GET` | `GET /{id}` | `POST /query` | `GET /export` | `DELETE /purge` | `GET /stats`

### 72. `/api/v1/memory-enhancement` — `memory_enhancement.py` | 需认证
- `GET` | `POST /consolidate` | `POST /summarize` | `POST /forget` | `GET /suggestions` | `POST /auto-organize`

### 73. `/api/v1/audio` — `audio.py` | 需认证
- `POST /transcribe` | `POST /synthesize` | `GET /voices` | `POST /process` | `GET /tasks/{id}`

### 74. `/api/v1/session-sync` — `session_sync.py` | 需认证
- `POST /sync` | `GET /status` | `GET /devices` | `POST /conflicts/resolve` | `DELETE /reset`

### 75. `/api/v1/memory-share-groups` — `memory_share_groups.py` | 需认证
- CRUD + members + `POST /{id}/memories`

### 76. `/api/v1/language` — `language_api.py` | 需认证（写面另加管理员门）
- 本人语言偏好：`GET /preferences/mine`（只读，没设过如实回 `configured:false`，不替用户建一条）｜
  `PUT /preferences/mine`（属主**只从登录态取**，请求体 `extra="forbid"`，多写 `user_id` 直接 422）
- 开箱默认（§6-167 取进来的那一格）：`GET /preferences/default`（登录即可读）｜`PUT /preferences/default`（**仅管理员**）
  它只作用于**还没自己选过语言的人**，本人一旦选过就以其本人偏好为准；落盘是 `language_preferences.json` 顶层的**可选 `default` 键**——不占 `preferences` 里的用户行（占了就会被读成「这个人做过决定」），也**不抬存储版本**（抬了会让已落盘的按人偏好被自己的版本隔离逻辑改名隔离，那是凭空丢真数据）
- 读数把两件事分开给：`configured`＝这个人自己做过决定没；`source` ∈ `user`/`out_of_box`/`builtin`＝这条读数是哪个来源给的。来源词汇只在 `LanguageManager.EFFECTIVE_SOURCES` 定义一处（UI 侧那份常量只在 `NeurUI/src/api/modules/language.ts`，判据按文件面钉住）
- 译文覆盖层：`GET /overlay?language=&namespace=`（含**未审**条目，逐条带 `approved`/`translator`）｜
  `PUT /overlay/{namespace}`（**仅管理员**；`{key: {语言码: 文案}}`，坏语言码整批 400 并点名）
- 语言码归一只走 `Language.normalizeTag`（本面不写第二刀）；`auto` 不许当首选/回退语言，
  那一层语义由 `auto_detect` 承载（台账 §6-140/§6-145 的同一根因，别在新字段上重建）
- 偏好落盘：数据根下 `language_preferences.json`（**刻意不放进 `language/` 译文目录**——
  那里每个 `*.json` 都会被当成一个命名空间读进来）；写盘失败回 500 且内存回滚，不谎报已保存
- 实测：无凭证各读面均 401、普通用户写面 403（活体 `tests/manual/languageFace_batch14.py`
  第 [22]/[13] 项，台账 §6-160）；`/preferences/default` 那两面同样实测——非管理员写 403、无凭证读 401（活体 `tests/manual/languageFace_outOfBox_batch167.py` 第 [4]/[19] 项，台账 §6-167）

---

## 附录

### 认证需求总结

> **本表已停用（2026-10-22，§6-399）**：原先按"模块"给出「无需认证」名单，实测**系统性错误**。
> 复算口径：真 `create_app()`，按 `include_context` 展开（顶层 `_IncludedRouter.path` 为空，
> 直接读它会得到"零路由"的假读数），逐路由读依赖图里的身份/角色门；**不请求任何端点**。
> 读数：附录列的 60 个模块中 56 个能在 `/api/v1/<module>` 找到路由，其中**只有 `health` 是
> 全公开**、**55 个至少有一条路由需认证**；这些前缀共 972 条路由，**542 条需认证、45 条公开**。
> 同一份文件里 `settings` 仍留在「无需认证」行，而它的模块节已写「需认证」并抄了实测 401——
> 手写汇总与模块节自相矛盾，这就是停用的原因。
>
> **以各模块节的标题为准。**「哪些端点公开」将由生成器按路由依赖图产出（下一批，含
> freshness 守卫），不再手写；生成器落地前，要确认某个面就看该模块节，或无凭证打一条
> **已存在**的路由（401/403＝有门；404/405 不算门，别把"路径写错"读成"没门"）。

仍有据可查的两条归类（来自模块节，不由本表推导）：

| 认证类型 | 模块 |
|----------|------|
| **API Key** | `agent-communication` |
| **HTTPBearer** | `mobile` |

### 公开面清单（机器段）

<!-- auth-surface:begin -->
> 本段由 `scripts/generate_api_auth_surface.py`（`--write`）生成，**不要手改**：
> 守卫 `tests/unit/api/test_authSurfaceFreshness.py` 逐字比对，漂移即红。
> 口径：只认**路由依赖图**里的身份/角色门；在 handler 体内自验 token 的那一类**未覆盖**，要确认它只能真打请求。404/405 不算门。

**汇总**：路由 958 条（含方法展开）——需认证 **851**、公开 **107**。

| 模块前缀 | 路由 | 需认证 | 公开 |
|----------|------|--------|------|
| `agent-communication` | 12 | 12 | 0 |
| `agent-enhancement` | 4 | 4 | 0 |
| `agents` | 15 | 12 | 3 |
| `analytics` | 4 | 4 | 0 |
| `api` | 32 | 15 | 17 |
| `artifacts` | 2 | 2 | 0 |
| `audio` | 7 | 2 | 5 |
| `audit` | 4 | 4 | 0 |
| `auth` | 10 | 0 | 10 |
| `backups` | 3 | 3 | 0 |
| `benchmark` | 14 | 14 | 0 |
| `budgets` | 7 | 0 | 7 |
| `builder` | 5 | 5 | 0 |
| `channel-adapters` | 10 | 8 | 2 |
| `channel-configs` | 16 | 16 | 0 |
| `channel-sharing` | 7 | 7 | 0 |
| `chat` | 6 | 6 | 0 |
| `collaboration` | 23 | 15 | 8 |
| `computer` | 25 | 25 | 0 |
| `computers` | 11 | 8 | 3 |
| `console` | 26 | 26 | 0 |
| `context` | 9 | 3 | 6 |
| `cost-rollup` | 8 | 0 | 8 |
| `enhanced-memory-search` | 11 | 6 | 5 |
| `enhanced-users` | 8 | 8 | 0 |
| `evolution` | 13 | 13 | 0 |
| `experience` | 7 | 7 | 0 |
| `files` | 12 | 12 | 0 |
| `firewall` | 6 | 6 | 0 |
| `generation` | 10 | 10 | 0 |
| `governance` | 26 | 26 | 0 |
| `groups` | 8 | 8 | 0 |
| `growth` | 13 | 13 | 0 |
| `health` | 6 | 0 | 6 |
| `home` | 2 | 2 | 0 |
| `image` | 5 | 5 | 0 |
| `knowledge` | 2 | 2 | 0 |
| `knowledge-graph` | 9 | 6 | 3 |
| `knowledge-integration` | 10 | 10 | 0 |
| `language` | 6 | 6 | 0 |
| `logs` | 4 | 4 | 0 |
| `logs-api` | 6 | 6 | 0 |
| `marketplace` | 12 | 12 | 0 |
| `media` | 15 | 15 | 0 |
| `memory` | 65 | 65 | 0 |
| `memory-enhancement` | 6 | 6 | 0 |
| `memory-settings` | 7 | 7 | 0 |
| `memory-share-groups` | 11 | 11 | 0 |
| `memory-timeline` | 4 | 4 | 0 |
| `metacognition` | 7 | 7 | 0 |
| `mobile` | 6 | 5 | 1 |
| `models` | 15 | 14 | 1 |
| `monitor` | 5 | 5 | 0 |
| `negative-screen` | 4 | 4 | 0 |
| `neurflow` | 47 | 31 | 16 |
| `notifications` | 9 | 9 | 0 |
| `openplatform` | 8 | 8 | 0 |
| `phase3` | 15 | 15 | 0 |
| `plans` | 6 | 6 | 0 |
| `plugins` | 24 | 24 | 0 |
| `projects` | 15 | 15 | 0 |
| `providers` | 13 | 13 | 0 |
| `quality` | 4 | 4 | 0 |
| `rules` | 8 | 8 | 0 |
| `runtime` | 4 | 4 | 0 |
| `sandbox` | 8 | 8 | 0 |
| `scheduler` | 7 | 7 | 0 |
| `semantic-search` | 5 | 4 | 1 |
| `settings` | 13 | 13 | 0 |
| `shared-config` | 14 | 14 | 0 |
| `skill-pool` | 37 | 37 | 0 |
| `skill-versions` | 8 | 8 | 0 |
| `skills` | 8 | 8 | 0 |
| `sleep` | 14 | 14 | 0 |
| `stats` | 9 | 5 | 4 |
| `studio` | 21 | 21 | 0 |
| `sync` | 8 | 7 | 1 |
| `synonyms` | 12 | 12 | 0 |
| `tasks` | 8 | 8 | 0 |
| `teams` | 10 | 10 | 0 |
| `tool-layers` | 13 | 13 | 0 |
| `tools` | 7 | 7 | 0 |
| `trace` | 5 | 5 | 0 |
| `user-groups` | 5 | 5 | 0 |
| `webhooks` | 7 | 7 | 0 |
| `workspace` | 5 | 5 | 0 |

**依赖图里未见身份门的路由（候选集，不等于「无凭证可打」）**：

- `POST /api/coordination/ab-tests/assign`
- `POST /api/coordination/ab-tests/end/{experiment_name}`
- `GET /api/coordination/ab-tests/list`
- `POST /api/coordination/ab-tests/record-metric`
- `POST /api/coordination/ab-tests/reset`
- `GET /api/coordination/ab-tests/results/{experiment_name}`
- `POST /api/coordination/ab-tests/start`
- `GET /api/coordination/summary`
- `POST /api/coordination/triage/check`
- `POST /api/coordination/triage/clear-cache`
- `POST /api/coordination/triage/reset`
- `GET /api/coordination/triage/stats`
- `POST /api/coordination/yield-checker/check`
- `POST /api/coordination/yield-checker/register-agent`
- `POST /api/coordination/yield-checker/reset`
- `GET /api/coordination/yield-checker/stats`
- `POST /api/coordination/yield-checker/unregister-agent`
- `GET /api/v1/agents/{agent_id}/constitution`
- `POST /api/v1/agents/{agent_id}/decision`
- `GET /api/v1/agents/{agent_id}/stats`
- `GET /api/v1/audio/engines`
- `GET /api/v1/audio/status`
- `POST /api/v1/audio/synthesize`
- `POST /api/v1/audio/synthesize-stream`
- `POST /api/v1/audio/transcribe`
- `POST /api/v1/auth/login`
- `POST /api/v1/auth/logout`
- `GET /api/v1/auth/me`
- `POST /api/v1/auth/recover-password`
- `POST /api/v1/auth/refresh`
- `POST /api/v1/auth/register`
- `POST /api/v1/auth/register/invite`
- `POST /api/v1/auth/register/send-code`
- `POST /api/v1/auth/register/verify-code`
- `GET /api/v1/auth/setup-status`
- `GET /api/v1/budgets/alerts`
- `POST /api/v1/budgets/alerts/config/update`
- `GET /api/v1/budgets/health`
- `POST /api/v1/budgets/record`
- `GET /api/v1/budgets/status/all`
- `GET /api/v1/budgets/status/{agent_id}`
- `GET /api/v1/budgets/{scope}/{identifier}/status`
- `GET /api/v1/channel-adapters/health/all`
- `POST /api/v1/channel-adapters/{channel_type}/webhook`
- `GET /api/v1/collaboration/history`
- `GET /api/v1/collaboration/sessions`
- `GET /api/v1/collaboration/stats`
- `GET /api/v1/collaboration/templates`
- `POST /api/v1/collaboration/templates`
- `DELETE /api/v1/collaboration/templates/{template_id}`
- `GET /api/v1/collaboration/templates/{template_id}`
- `PUT /api/v1/collaboration/templates/{template_id}`
- `POST /api/v1/computers/cleanup-offline`
- `GET /api/v1/computers/cloud`
- `POST /api/v1/computers/{computer_id}/heartbeat`
- `GET /api/v1/context/inject/hot`
- `GET /api/v1/context/inject/memories`
- `GET /api/v1/context/inject/reflection`
- `GET /api/v1/context/stats`
- `POST /api/v1/context/{context_id}/compress`
- `GET /api/v1/context/{context_id}/preview`
- `GET /api/v1/cost-rollup/agent/{agent_id}/cost`
- `GET /api/v1/cost-rollup/dashboard/metrics`
- `GET /api/v1/cost-rollup/history/daily`
- `GET /api/v1/cost-rollup/history/hourly`
- `GET /api/v1/cost-rollup/queries/{query_name}`
- `POST /api/v1/cost-rollup/rollup/now`
- `POST /api/v1/cost-rollup/rollup/range`
- `GET /api/v1/cost-rollup/rollup/status`
- `GET /api/v1/enhanced-memory-search/activation/{memory_id}`
- `POST /api/v1/enhanced-memory-search/analyze`
- `POST /api/v1/enhanced-memory-search/decay`
- `POST /api/v1/enhanced-memory-search/search`
- `GET /api/v1/enhanced-memory-search/stats`
- `GET /api/v1/health`
- `GET /api/v1/health/checks`
- `GET /api/v1/health/checks/{name}`
- `POST /api/v1/health/checks/{name}/run`
- `POST /api/v1/health/recover`
- `GET /api/v1/health/report`
- `GET /api/v1/knowledge-graph/{agent_id}/knowledge-graph`
- `GET /api/v1/knowledge-graph/{agent_id}/knowledge-graph/nodes/{node_id}`
- `GET /api/v1/knowledge-graph/{agent_id}/knowledge-graph/search`
- `POST /api/v1/mobile/pairing/confirm`
- `GET /api/v1/models/active`
- `GET /api/v1/neurflow/agents`
- `POST /api/v1/neurflow/agents`
- `POST /api/v1/neurflow/agents/{agent_id}/archive`
- `POST /api/v1/neurflow/agents/{agent_id}/restore`
- `POST /api/v1/neurflow/comfyui/execute`
- `GET /api/v1/neurflow/comfyui/status`
- `GET /api/v1/neurflow/executions`
- `GET /api/v1/neurflow/executions/{execution_id}`
- `POST /api/v1/neurflow/executions/{execution_id}/cancel`
- `GET /api/v1/neurflow/nodes`
- `GET /api/v1/neurflow/nodes/search/{query}`
- `GET /api/v1/neurflow/nodes/stats`
- `POST /api/v1/neurflow/nodes/sync`
- `GET /api/v1/neurflow/nodes/{node_type:path}`
- `GET /api/v1/neurflow/otel/status`
- `GET /api/v1/neurflow/stats`
- `POST /api/v1/semantic-search/analyze`
- `GET /api/v1/stats`
- `GET /api/v1/stats/performance`
- `GET /api/v1/stats/token-usage`
- `GET /api/v1/stats/usage`
- `GET /api/v1/sync/statistics`
<!-- auth-surface:end -->

> **抽样复核（裁定 C，2026-10-22）**：对机器段里 49 条安全的 GET 逐条以无凭证真打（隔离数据根）
> ——校准格 `GET /api/v1/settings` 回 401；49 条中 **2 条回 401**：`GET /api/v1/auth/me`、
> `GET /api/v1/computers/cloud`。它们正是「handler 体内自验」那一类（依赖图里看不到门），
> 所以上面的清单是**候选集**、不是「无凭证可打」的证明；判定某个面请以真打为准。
> 复跑：`tests/manual/authSurfacePublicProbe_batch.py`。

> 脚注（§6-158）：`media` 原先挂在"无需认证"那一行，与实况不符——`media.py:40` 是
> `APIRouter(dependencies=[Depends(get_current_user)])`，无凭证请求实测回 **401**
> （活体第 [8] 项）。这张表**没有逐模块复核过**，其余条目同样可能是旧的：本批只按实测改了
> 自己动过的那一格，不做整表顺手清扫（那需要一次自己的复算与裁定，登记在台账）。
>
> 追加（§6-160）：`language` 这一行是**按实测新加的**，不是照旧表抄的——两个读面无凭证 401、
> 覆盖层写面对普通用户 403（活体第 [22]/[13] 项）。旧表那张"无需认证"名单至今仍未逐模块复核。

### 项目统计

| 指标 | 数值 |
|------|------|
| 后端API模块 | 76 |
| 端点总数 | 625+ |
| GET端点 | ~250 |
| POST端点 | ~250 |
| PUT端点 | ~50 |
| DELETE端点 | ~50 |
| 需认证端点 | 未复核（旧读数「~100」已不可采信，见上方停用说明） |
| 公开端点 | 未复核（旧读数「~525」与实测相反：同口径下公开仅 45） |
| 前端覆盖 | 94.7% (71/75) |

> 除注明外，本表为 2026-09 的旧统计，未经生成器复核；认证两行已停用（§6-399）。

---

> **文档结束** — Neurova API Reference v1.0.0-beta1