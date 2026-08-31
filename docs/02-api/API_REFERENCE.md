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

### 10. `/api/v1/settings` — `settings.py` | 无认证
- `GET/PUT` 系统设置 | `GET/PUT /llm` LLM配置 | `POST /llm/test` 测试

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
- `POST /upload` | `GET` 列表 | `GET /{id}` | `DELETE /{id}`

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

### 47. `/api/v1/skills-market` — `skill_market.py` + `skills_market.py`
- `GET` | `GET /{id}` | `POST /{id}/install` | `POST /publish` | `GET /categories`

### 48. `/api/v1/skill-versions` — `skill_version_api.py`
- `GET` | `GET /{id}` | `POST /{id}/rollback`

### 49. `/api/v1/mobile` — `mobile_pairing.py` | 需认证
- `POST /pairing/generate` | `GET /pairing/qrcode/{code}` | `POST /pairing/confirm` | `GET /pairing/status/{code}` | `GET /pairing/list` | `DELETE /pairing/{id}` | `WS /ws`

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

---

## 附录

### 认证需求总结

| 认证类型 | 模块 |
|----------|------|
| **无需认证** | health, home, chat, agents, models, providers, skills, settings, logs, stats, monitor, scheduler, trace, generation, image, media, knowledge, growth, sleep, runtime, marketplace, channels, channel-adapters, channel-configs, channel-sharing, notifications, audit, firewall, analytics, collaboration, groups, teams, workflows, tasks, projects, rules, webhooks, enhanced-users, user-groups, files, file-flows, tools, tool-layers, skill-pool, skills-market, skill-versions, benchmark, console, plugins, sandbox, builder, computer, shared-config, openplatform, model-adapter, experience, knowledge-graph, knowledge-integration, semantic-search, enhanced-memory-search, memory-timeline, synonyms |
| **JWT Token** | auth(me), memory子模块, context, context-pool, metacognition, agent-enhancement, logs-api, memory-enhancement, audio, session-sync, memory-share-groups |
| **API Key** | agent-communication |
| **HTTPBearer** | mobile |

### 项目统计

| 指标 | 数值 |
|------|------|
| 后端API模块 | 75 |
| 端点总数 | 625+ |
| GET端点 | ~250 |
| POST端点 | ~250 |
| PUT端点 | ~50 |
| DELETE端点 | ~50 |
| 需认证端点 | ~100 |
| 公开端点 | ~525 |
| 前端覆盖 | 94.7% (71/75) |

---

> **文档结束** — Neurova API Reference v1.0.0-beta1