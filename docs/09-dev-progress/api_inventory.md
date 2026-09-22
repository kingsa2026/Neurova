# Neurova 前端 API 清单（生成物）

> **生成命令**：`python scripts/generate_api_inventory.py --write`
> **快照日期**：2026-09-22
> **事实源**：前端模块 `NeurUI/src/api/modules/`；后端端点 `neurova/api/endpoints/`
> （注册表 `neurova/api/endpoints/__init__.py` 加 `neurova/api/app.py` 直接挂载）。
> 本表**由脚本产出，不要手改**；接口报文与字段以 [API_REFERENCE.md](../02-api/API_REFERENCE.md) 为准。

过期判据不是日历而是**双向差集**：代码树增删一个模块，本表与代码树的差集即非空，守卫 `tests/unit/test_api_inventory_freshness_guard.py` 立刻报红并给出差集两侧的名单。

<!-- API-INVENTORY:BEGIN -->
## 一、前端 API 模块（61 个）

| 模块文件 | 消费的后端前缀 | barrel 导出 | 仓内引用处 |
|------|------|------|------|
| `NeurUI/src/api/modules/agent-communication.ts` | `/agent-communication` | 是 | 1 |
| `NeurUI/src/api/modules/agent-enhancement.ts` | `/agent-enhancement` | 是 | 1 |
| `NeurUI/src/api/modules/agent-package.ts` | `/agents` | 是 | 1 |
| `NeurUI/src/api/modules/analytics.ts` | `/analytics` | 是 | 4 |
| `NeurUI/src/api/modules/audit.ts` | `/audit` | 是 | 1 |
| `NeurUI/src/api/modules/builder.ts` | `/builder` | 是 | 1 |
| `NeurUI/src/api/modules/channel-configs.ts` | `/channel-adapters`, `/channel-configs` | 是 | 5 |
| `NeurUI/src/api/modules/collaboration.ts` | `/collaboration`, `/neurflow` | 是 | 23 |
| `NeurUI/src/api/modules/collaborationRoom.ts` | `/collaboration` | **否** | 2 |
| `NeurUI/src/api/modules/computer.ts` | `/computer` | 是 | 2 |
| `NeurUI/src/api/modules/console.ts` | `/console` | 是 | 5 |
| `NeurUI/src/api/modules/context-pool.ts` | `/context-pool` | 是 | 1 |
| `NeurUI/src/api/modules/context.ts` | `/context` | 是 | 1 |
| `NeurUI/src/api/modules/cost.ts` | `/budgets`, `/cost-rollup` | **否** | 2 |
| `NeurUI/src/api/modules/enhanced-users.ts` | `/enhanced-users` | 是 | 0 |
| `NeurUI/src/api/modules/experience.ts` | `/experience` | 是 | 4 |
| `NeurUI/src/api/modules/files.ts` | `/files` | 是 | 7 |
| `NeurUI/src/api/modules/firewall.ts` | `/firewall` | 是 | 2 |
| `NeurUI/src/api/modules/generation.ts` | `/generation` | 是 | 6 |
| `NeurUI/src/api/modules/governance.ts` | `/governance` | **否** | 3 |
| `NeurUI/src/api/modules/groups.ts` | `/groups` | 是 | 2 |
| `NeurUI/src/api/modules/growth.ts` | `/growth` | 是 | 5 |
| `NeurUI/src/api/modules/health.ts` | `/health` | 是 | 5 |
| `NeurUI/src/api/modules/home.ts` | `/home` | 是 | 3 |
| `NeurUI/src/api/modules/image.ts` | `/image` | 是 | 1 |
| `NeurUI/src/api/modules/knowledge.ts` | `/knowledge`, `/knowledge-graph`, `/semantic-search` | 是 | 9 |
| `NeurUI/src/api/modules/logs-api.ts` | `/logs-api` | 是 | 1 |
| `NeurUI/src/api/modules/media.ts` | `/media` | 是 | 1 |
| `NeurUI/src/api/modules/memory-settings.ts` | `/memory-settings` | 是 | 4 |
| `NeurUI/src/api/modules/memory.ts` | `/enhanced-memory-search`, `/memory`, `/memory-enhancement`, `/memory-share-groups`, `/memory-timeline`, `/semantic-search` | 是 | 14 |
| `NeurUI/src/api/modules/metacognition.ts` | `/metacognition` | 是 | 4 |
| `NeurUI/src/api/modules/mobile.ts` | `/mobile` | 是 | 1 |
| `NeurUI/src/api/modules/model-adapter.ts` | `/model-adapter` | 是 | 1 |
| `NeurUI/src/api/modules/models.ts` | `/models` | 是 | 12 |
| `NeurUI/src/api/modules/negative-screen.ts` | `/negative-screen`, `/notifications` | 是 | 5 |
| `NeurUI/src/api/modules/neurflow.ts` | `/neurflow` | 是 | 8 |
| `NeurUI/src/api/modules/notifications.ts` | `/notifications` | 是 | 6 |
| `NeurUI/src/api/modules/openplatform.ts` | `/openplatform` | 是 | 0 |
| `NeurUI/src/api/modules/plans.ts` | `/plans` | 是 | 3 |
| `NeurUI/src/api/modules/plugins.ts` | `/plugins` | 是 | 0 |
| `NeurUI/src/api/modules/projects.ts` | `/projects` | 是 | 5 |
| `NeurUI/src/api/modules/providers.ts` | `/providers` | 是 | 11 |
| `NeurUI/src/api/modules/rsiGovernance.ts` | `/governance` | **否** | 2 |
| `NeurUI/src/api/modules/rules.ts` | `/rules` | 是 | 1 |
| `NeurUI/src/api/modules/runtime.ts` | `/runtime` | 是 | 1 |
| `NeurUI/src/api/modules/sandbox.ts` | `/sandbox` | 是 | 0 |
| `NeurUI/src/api/modules/scheduler.ts` | `/scheduler` | 是 | 3 |
| `NeurUI/src/api/modules/settings.ts` | `/governance`, `/settings` | 是 | 7 |
| `NeurUI/src/api/modules/shared-config.ts` | `/shared-config` | 是 | 0 |
| `NeurUI/src/api/modules/skill-pool.ts` | `/marketplace`, `/skill-pool` | 是 | 9 |
| `NeurUI/src/api/modules/sleep.ts` | `/sleep` | 是 | 8 |
| `NeurUI/src/api/modules/stats.ts` | `/stats` | 是 | 6 |
| `NeurUI/src/api/modules/studio.ts` | `/studio` | **否** | 6 |
| `NeurUI/src/api/modules/synonyms.ts` | `/synonyms` | 是 | 1 |
| `NeurUI/src/api/modules/system-logs.ts` | `/logs` | 是 | 1 |
| `NeurUI/src/api/modules/tasks.ts` | `/tasks` | 是 | 0 |
| `NeurUI/src/api/modules/teams.ts` | `/teams` | 是 | 2 |
| `NeurUI/src/api/modules/text-evolution.ts` | `/evolution` | **否** | 2 |
| `NeurUI/src/api/modules/tool-layers.ts` | `/tool-layers` | 是 | 2 |
| `NeurUI/src/api/modules/trace.ts` | `/trace` | 是 | 2 |
| `NeurUI/src/api/modules/webhooks.ts` | `/webhooks` | 是 | 1 |

> `NeurUI/src/api/index.ts` 是 axios 实例与鉴权拦截器，`NeurUI/src/api/auth.ts` / `NeurUI/src/api/neuron.ts` 是模块目录之外的单文件客户端，三者不属本表模块口径。

## 二、后端挂载前缀（90 条）

| 端点模块 | 挂载前缀 |
|------|------|
| `neurova/api/endpoints/__init__.py` | `/api/acp` |
| `neurova/api/endpoints/agent.py` | `/api/v1/agents` |
| `neurova/api/endpoints/agent_communication_api.py` | `/api/v1/agent-communication` |
| `neurova/api/endpoints/agent_enhancement.py` | `/api/v1/agent-enhancement` |
| `neurova/api/endpoints/agent_package.py` | `/api/v1/agents` |
| `neurova/api/endpoints/analytics.py` | `/api/v1/analytics` |
| `neurova/api/endpoints/artifacts_api.py` | `/api/v1/artifacts` |
| `neurova/api/endpoints/audio.py` | `/api/v1/audio` |
| `neurova/api/endpoints/audit.py` | `/api/v1/audit` |
| `neurova/api/endpoints/auth.py` | `/api/v1/auth` |
| `neurova/api/endpoints/backup_api.py` | `/api/v1/backups` |
| `neurova/api/endpoints/benchmark.py` | `/api/v1/benchmark` |
| `neurova/api/endpoints/budget_api.py` | `/api/budgets` |
| `neurova/api/endpoints/builder.py` | `/api/v1/builder` |
| `neurova/api/endpoints/channel_config.py` | `/api/v1/channel-configs` |
| `neurova/api/endpoints/channel_sharing.py` | `/api/v1/channel-sharing` |
| `neurova/api/endpoints/channels.py` | `/api/v1/channel-adapters` |
| `neurova/api/endpoints/chat.py` | `/api/v1/chat` |
| `neurova/api/endpoints/collaboration_api.py` | `/api/v1/collaboration` |
| `neurova/api/endpoints/collaboration_room_api.py` | `/api/v1/collaboration` |
| `neurova/api/endpoints/computer.py` | `/api/v1/computer` |
| `neurova/api/endpoints/console.py` | `/api/v1/console` |
| `neurova/api/endpoints/context.py` | `/api/v1/context` |
| `neurova/api/endpoints/context_pool_settings.py` | `/api/v1/context-pool` |
| `neurova/api/endpoints/coordination_api.py` | `/api/coordination/coordination` |
| `neurova/api/endpoints/cost_rollup_api.py` | `/api/cost-rollup` |
| `neurova/api/endpoints/enhanced_memory_search_api.py` | `/api/v1/enhanced-memory-search` |
| `neurova/api/endpoints/enhanced_users_api.py` | `/api/v1/enhanced-users` |
| `neurova/api/endpoints/experience_knowledge_api.py` | `/api/v1/experience` |
| `neurova/api/endpoints/files_api.py` | `/api/v1/files` |
| `neurova/api/endpoints/firewall.py` | `/api/v1/firewall` |
| `neurova/api/endpoints/generation.py` | `/api/v1/generation` |
| `neurova/api/endpoints/governance.py` | `/api/v1/governance` |
| `neurova/api/endpoints/groups_api.py` | `/api/v1/groups` |
| `neurova/api/endpoints/growth.py` | `/api/v1/growth` |
| `neurova/api/endpoints/health.py` | `/api/v1/health` |
| `neurova/api/endpoints/home.py` | `/api/v1` |
| `neurova/api/endpoints/image.py` | `/api/v1/image` |
| `neurova/api/endpoints/knowledge.py` | `/api/v1/knowledge` |
| `neurova/api/endpoints/knowledge_graph_api.py` | `/api/v1/knowledge-graph` |
| `neurova/api/endpoints/knowledge_integration.py` | `/api/v1/knowledge-integration` |
| `neurova/api/endpoints/logs.py` | `/api/v1/logs` |
| `neurova/api/endpoints/logs_api.py` | `/api/v1/logs-api` |
| `neurova/api/endpoints/marketplace.py` | `/api/v1/marketplace` |
| `neurova/api/endpoints/mcp_server_api.py` | `/api/v1/mcp` |
| `neurova/api/endpoints/media.py` | `/api/v1/media` |
| `neurova/api/endpoints/memory/__init__.py` | `/api/v1/memory` |
| `neurova/api/endpoints/memory_enhancement.py` | `/api/v1/memory-enhancement` |
| `neurova/api/endpoints/memory_settings_api.py` | `/api/v1/memory-settings` |
| `neurova/api/endpoints/memory_share_groups.py` | `/api/v1/memory-share-groups` |
| `neurova/api/endpoints/memory_timeline_api.py` | `/api/v1/memory-timeline` |
| `neurova/api/endpoints/metacognition_api.py` | `/api/v1/metacognition` |
| `neurova/api/endpoints/mobile_pairing.py` | `/api/v1/mobile` |
| `neurova/api/endpoints/model.py` | `/api/v1/models` |
| `neurova/api/endpoints/model_adapter.py` | `/api/v1/model-adapter` |
| `neurova/api/endpoints/monitor.py` | `/api/v1/monitor` |
| `neurova/api/endpoints/negative_screen_settings.py` | `/api/v1/negative-screen` |
| `neurova/api/endpoints/neurflow_api.py` | `/api/v1/neurflow` |
| `neurova/api/endpoints/neuron.py` | `/api/neuron` |
| `neurova/api/endpoints/neuron.py` | `/api/neuron/neuron` |
| `neurova/api/endpoints/notifications.py` | `/api/v1/notifications` |
| `neurova/api/endpoints/openplatform_keys.py` | `/api/v1/openplatform` |
| `neurova/api/endpoints/plans.py` | `/api/v1/plans` |
| `neurova/api/endpoints/plugin.py` | `/api/v1/plugins` |
| `neurova/api/endpoints/projects_api.py` | `/api/v1/projects` |
| `neurova/api/endpoints/provider.py` | `/api/v1/providers` |
| `neurova/api/endpoints/rules_api.py` | `/api/v1/rules` |
| `neurova/api/endpoints/runtime.py` | `/api/v1/runtime` |
| `neurova/api/endpoints/sandbox.py` | `/api/v1/sandbox` |
| `neurova/api/endpoints/scheduler.py` | `/api/v1/scheduler` |
| `neurova/api/endpoints/semantic_search_api.py` | `/api/v1/semantic-search` |
| `neurova/api/endpoints/session_sync.py` | `/api/v1/sync` |
| `neurova/api/endpoints/settings.py` | `/api/v1/settings` |
| `neurova/api/endpoints/shared_config.py` | `/api/v1/shared-config` |
| `neurova/api/endpoints/skill.py` | `/api/v1/skills` |
| `neurova/api/endpoints/skill_pool_api.py` | `/api/v1/skill-pool` |
| `neurova/api/endpoints/skill_version_api.py` | `/api/v1/skill-versions` |
| `neurova/api/endpoints/sleep.py` | `/api/v1/sleep` |
| `neurova/api/endpoints/stats.py` | `/api/v1/stats` |
| `neurova/api/endpoints/studio_api.py` | `/api/v1/studio` |
| `neurova/api/endpoints/synonym_api.py` | `/api/v1/synonyms` |
| `neurova/api/endpoints/tasks_api.py` | `/api/v1/tasks` |
| `neurova/api/endpoints/teams_api.py` | `/api/v1/teams` |
| `neurova/api/endpoints/text_evolution_api.py` | `/api/v1/evolution` |
| `neurova/api/endpoints/tool_layers.py` | `/api/v1/tool-layers` |
| `neurova/api/endpoints/tool_schema.py` | `/api/v1/tools` |
| `neurova/api/endpoints/trace.py` | `/api/v1/trace` |
| `neurova/api/endpoints/user_group_api.py` | `/api/v1/user-groups` |
| `neurova/api/endpoints/webhooks.py` | `/api/v1/webhooks` |
| `neurova/api/endpoints/workspace_files.py` | `/api/v1/workspace` |

## 三、差集（断点以显式名单暴露，不用「大致一致」带过）

**barrel 未导出的模块**：`NeurUI/src/api/modules/collaborationRoom.ts`, `NeurUI/src/api/modules/cost.ts`, `NeurUI/src/api/modules/governance.ts`, `NeurUI/src/api/modules/rsiGovernance.ts`, `NeurUI/src/api/modules/studio.ts`, `NeurUI/src/api/modules/text-evolution.ts`

**前后端前缀契约断点**（前端按 `baseURL=/api/v1` 请求，后端无对应挂载点 → 404）：`NeurUI/src/api/modules/cost.ts` 请求 `/api/v1/budgets`, `NeurUI/src/api/modules/cost.ts` 请求 `/api/v1/cost-rollup`

**零路由挂载点**（注册动作在、路由一条没有 —— 断点，待接线或删除）：`/api/evolution`, `/api/rag`

**未接线 router**（含被旁路注册掩盖的顶层空对象）：`neurova/api/endpoints/__init__.py` 的 `evolution_router`（挂 `/api/evolution`）, `neurova/api/endpoints/__init__.py` 的 `rag_router`（挂 `/api/rag`）, `neurova/api/endpoints/__init__.py` 的 `router`（挂 `/api`）

**后端已注册、前端无模块直连的挂载点**（内部/平台面，通常由控制台或 SDK 消费）：`/api/acp`, `/api/budgets`, `/api/coordination/coordination`, `/api/cost-rollup`, `/api/neuron`, `/api/neuron/neuron`, `/api/v1/artifacts`, `/api/v1/audio`, `/api/v1/auth`, `/api/v1/backups`, `/api/v1/benchmark`, `/api/v1/channel-sharing`, `/api/v1/chat`, `/api/v1/knowledge-integration`, `/api/v1/mcp`, `/api/v1/monitor`, `/api/v1/skill-versions`, `/api/v1/skills`, `/api/v1/sync`, `/api/v1/tools`, `/api/v1/user-groups`, `/api/v1/workspace`


## 四、前端调用 ↔ 后端注册 差集

下列 **67** 处调用在本轮后端注册表里没有对应路由。这不等于「后端漏注册」——差异以显式列表暴露，由人去核：

| 模块 | 方法 | 调用路径 | 差异形态 |
|------|------|------|------|
| computer | GET | `/api/computers` | 路径未注册 |
| computer | POST | `/api/computers` | 路径未注册 |
| computer | DELETE | `/api/computers/*` | 路径未注册 |
| computer | GET | `/api/computers/*` | 路径未注册 |
| computer | GET | `/api/computers/*/agents` | 路径未注册 |
| computer | POST | `/api/computers/*/heartbeat` | 路径未注册 |
| computer | POST | `/api/computers/*/pair` | 路径未注册 |
| computer | POST | `/api/computers/*/revoke` | 路径未注册 |
| computer | POST | `/api/computers/cleanup-offline` | 路径未注册 |
| computer | GET | `/api/computers/cloud` | 路径未注册 |
| computer | GET | `/api/cost/agent/*/detailed` | 路径未注册 |
| computer | GET | `/api/cost/agent/*/summary` | 路径未注册 |
| computer | POST | `/api/cost/calculate` | 路径未注册 |
| computer | GET | `/api/cost/company/*/leaderboard` | 路径未注册 |
| computer | GET | `/api/cost/company/*/summary` | 路径未注册 |
| computer | GET | `/api/cost/dashboard/realtime` | 路径未注册 |
| computer | GET | `/api/cost/rollup/hourly` | 路径未注册 |
| console | POST | `/api/v1/console/debug` | 路径未注册 |
| console | POST | `/api/v1/console/push` | 路径未注册 |
| cost | GET | `/api/v1/budgets/health` | 路径未注册 |
| cost | GET | `/api/v1/budgets/status/*` | 路径未注册 |
| cost | GET | `/api/v1/budgets/status/all` | 路径未注册 |
| cost | GET | `/api/v1/cost-rollup/agent/*/cost` | 路径未注册 |
| cost | GET | `/api/v1/cost-rollup/dashboard/metrics` | 路径未注册 |
| cost | GET | `/api/v1/cost-rollup/history/daily` | 路径未注册 |
| cost | GET | `/api/v1/cost-rollup/history/hourly` | 路径未注册 |
| cost | POST | `/api/v1/cost-rollup/rollup/now` | 路径未注册 |
| cost | GET | `/api/v1/cost-rollup/rollup/status` | 路径未注册 |
| files | GET | `/api/v1/files/*/content` | 路径未注册 |
| health | GET | `/api/v1/health/metrics` | 路径未注册 |
| health | GET | `/api/v1/health/status` | 路径未注册 |
| knowledge | POST | `/api/v1/knowledge/annotations` | 方法不匹配 |
| knowledge | DELETE | `/api/v1/knowledge/annotations/*` | 路径未注册 |
| knowledge | PUT | `/api/v1/knowledge/annotations/*` | 路径未注册 |
| knowledge | GET | `/api/v1/knowledge/annotations/export` | 路径未注册 |
| memory | PUT | `/api/v1/memory/*` | 方法不匹配 |
| memory | POST | `/api/v1/memory/search` | 方法不匹配 |
| models | POST | `/api/v1/models` | 方法不匹配 |
| models | GET | `/api/v1/models/*` | 方法不匹配 |
| models | POST | `/api/v1/models/active` | 方法不匹配 |
| models | GET | `/api/v1/models/fetch` | 方法不匹配 |
| neurflow | POST | `/api/v1/neurflow/comfyui/import` | 路径未注册 |
| neuron | POST | `/api/v1/absence/detect` | 路径未注册 |
| neuron | POST | `/api/v1/cascade` | 路径未注册 |
| neuron | POST | `/api/v1/dependencies` | 路径未注册 |
| neuron | GET | `/api/v1/dependencies/*` | 路径未注册 |
| neuron | GET | `/api/v1/entities` | 路径未注册 |
| neuron | POST | `/api/v1/entities` | 路径未注册 |
| neuron | POST | `/api/v1/extract` | 路径未注册 |
| neuron | POST | `/api/v1/would-affect` | 路径未注册 |
| openplatform | POST | `/api/v1/openplatform/keys` | 方法不匹配 |
| openplatform | DELETE | `/api/v1/openplatform/keys/*` | 路径未注册 |
| openplatform | PUT | `/api/v1/openplatform/keys/*` | 路径未注册 |
| openplatform | POST | `/api/v1/openplatform/keys/*/rotate` | 路径未注册 |
| openplatform | GET | `/api/v1/openplatform/keys/*/usage` | 路径未注册 |
| plugins | POST | `/api/v1/plugins` | 方法不匹配 |
| plugins | DELETE | `/api/v1/plugins/*` | 方法不匹配 |
| plugins | PUT | `/api/v1/plugins/*` | 方法不匹配 |
| plugins | POST | `/api/v1/plugins/*/uninstall` | 方法不匹配 |
| plugins | GET | `/api/v1/plugins/discover` | 方法不匹配 |
| sandbox | POST | `/api/v1/sandbox/*/execute` | 路径未注册 |
| settings | POST | `/api/v1/settings/clear-cache` | 方法不匹配 |
| shared-config | POST | `/api/v1/shared-config/llm-providers/*/test` | 路径未注册 |
| shared-config | POST | `/api/v1/shared-config/mcp-servers/*/test` | 路径未注册 |
| system-logs | POST | `/api/v1/logs/clear` | 路径未注册 |
| tool-layers | POST | `/api/v1/tool-layers/tools/*/execute` | 路径未注册 |
| tool-layers | POST | `/api/v1/tool-layers/tools/install` | 路径未注册 |

## 五、后端已注册 ↔ 前端消费方 差集

下列 **21** 个后端挂载前缀无任何前端模块直连，属「后端已就位、前端待补消费方」的显式清单：

| 后端挂载前缀 |
|------|
| `/acp` |
| `/artifacts` |
| `/audio` |
| `/backups` |
| `/benchmark` |
| `/channel-sharing` |
| `/chat` |
| `/coordination` |
| `/frontend` |
| `/knowledge-integration` |
| `/mcp` |
| `/metrics` |
| `/monitor` |
| `/neuron` |
| `/skill-versions` |
| `/skills` |
| `/status` |
| `/sync` |
| `/tools` |
| `/user-groups` |
| `/workspace` |
<!-- API-INVENTORY:END -->

## 口径说明

1. **后台逐端点清单已退役**：旧表逐条列「方法 / 路径 / 功能 / 是否实现」，那是人工维护的第二份事实源，必然漂移。逐条端点以 `docs/02-api/API_REFERENCE.md`（接口事实源）与运行时 `/docs` 为准。
2. **导航归属**：本表定位仍是**现行清单**，保留在 `docs/0-index/README.md` 的 `09-dev-progress` 领域入口表内；重生成后其路径引用全部可解析，不再构成「指路条目」形态的失效引用。
3. **快照纪律**：头部生成日期与生成命令必须同时在场；超过约定周期未重生成时，以代码树差集（而非日期）判定是否过期。
