# 前端 API 面清单（生成物）

> **性质**：本清单由 `scripts/gen_api_inventory.py` 对**现行代码树**取全集产出，
> 机器区请勿手改。它是 `docs/0-index/README.md` 里的 `09-dev-progress` 领域入口——
> 存在意义是**把人指对地方**，因此唯一可接受的形态是「与代码树一致且可复算」。
>
> **与接口事实源的分工**：本清单是**前端视角**（哪个前端模块请求了哪些端点前缀、
> 哪些后端前缀还没有消费方）；接口本身的事实源是
> [`docs/02-api/API_REFERENCE.md`](../02-api/API_REFERENCE.md)。两者职责不同，不合并。

## 这份清单解决什么

历史版本是手写的「API 完整清单」，自 2026-06-06 起与代码树脱节：声明的模块近半已
改名或合并，另有一批现行模块根本没进清单。它坏掉的方式不是「没人维护」，而是
**压根没有生成入口**——代码树一变它只能漂移，且没有任何命令能把它拉回来。

故本清单改为生成物，判据只写一份（生成器内），由常驻守卫
（`tests/unit/test_api_inventory_guard.py`）重算比对。三件事因此变成机器可验：

1. **模块双向差集为空**：清单声明的模块与 `NeurUI/src/api/modules/*.ts` 一致；
2. **差异显式暴露**：前端调用未命中后端注册（区分「路径未注册」与「方法不匹配」）、
   后端前缀无前端消费，两组差异逐条列出，不删条目掩盖（删条目只是把洞换个位置，
   与「禁止表面抹除」同一条纪律）；
3. **快照纪律可核**：生成命令与快照日期写在机器区，逾期由守卫点名。

## 非目标

- 不改后端路由注册结构。清单只做**读**——发现差异就登记，不在本清单里顺手改代码；
- 不重写 `docs/02-api/API_REFERENCE.md`（接口视角与前端视角各司其职）。

<!-- 以下机器区由 `python scripts/gen_api_inventory.py --update` 生成 -->
<!-- API-INVENTORY:BEGIN -->
**生成命令**：`python scripts/gen_api_inventory.py --update`
**快照日期**：2026-09-22

本区为**生成物**，请勿手改；重跑上面的命令即可刷新。快照周期上限 120 天，逾期由守卫点名。

事实源：前端 `NeurUI/src/api/modules/*.ts`（61 个模块 · 674 处调用），后端 `create_app()` 装配后的真实路由表（830 条路由）。

## 一、前端 API 模块清单

| 模块 | 边界 | 请求到的一级前缀 | 调用数 |
|------|------|------|------|
| agent-communication | `NeurUI/src/api/modules/agent-communication.ts` | `/agent-communication` | 12 |
| agent-enhancement | `NeurUI/src/api/modules/agent-enhancement.ts` | `/agent-enhancement` | 4 |
| agent-package | `NeurUI/src/api/modules/agent-package.ts` | `/agents` | 2 |
| analytics | `NeurUI/src/api/modules/analytics.ts` | `/analytics` | 4 |
| audit | `NeurUI/src/api/modules/audit.ts` | `/audit` | 2 |
| builder | `NeurUI/src/api/modules/builder.ts` | `/builder` | 5 |
| channel-configs | `NeurUI/src/api/modules/channel-configs.ts` | `/channel-adapters`、`/channel-configs` | 11 |
| collaboration | `NeurUI/src/api/modules/collaboration.ts` | `/collaboration`、`/neurflow` | 32 |
| collaborationRoom | `NeurUI/src/api/modules/collaborationRoom.ts` | `/collaboration` | 4 |
| computer | `NeurUI/src/api/modules/computer.ts` | `/computer` | 9 |
| console | `NeurUI/src/api/modules/console.ts` | `/console` | 9 |
| context-pool | `NeurUI/src/api/modules/context-pool.ts` | `/context-pool` | 4 |
| context | `NeurUI/src/api/modules/context.ts` | `/context` | 10 |
| cost | `NeurUI/src/api/modules/cost.ts` | `/budgets`、`/cost-rollup` | 9 |
| enhanced-users | `NeurUI/src/api/modules/enhanced-users.ts` | `/enhanced-users` | 6 |
| experience | `NeurUI/src/api/modules/experience.ts` | `/experience` | 9 |
| files | `NeurUI/src/api/modules/files.ts` | `/files` | 7 |
| firewall | `NeurUI/src/api/modules/firewall.ts` | `/firewall` | 6 |
| generation | `NeurUI/src/api/modules/generation.ts` | `/generation` | 9 |
| governance | `NeurUI/src/api/modules/governance.ts` | `/governance` | 9 |
| groups | `NeurUI/src/api/modules/groups.ts` | `/groups` | 8 |
| growth | `NeurUI/src/api/modules/growth.ts` | `/growth` | 14 |
| health | `NeurUI/src/api/modules/health.ts` | `/health` | 5 |
| home | `NeurUI/src/api/modules/home.ts` | `/home` | 2 |
| image | `NeurUI/src/api/modules/image.ts` | `/image` | 5 |
| knowledge | `NeurUI/src/api/modules/knowledge.ts` | `/knowledge`、`/knowledge-graph`、`/semantic-search` | 42 |
| logs-api | `NeurUI/src/api/modules/logs-api.ts` | `/logs-api` | 6 |
| media | `NeurUI/src/api/modules/media.ts` | `/media` | 9 |
| memory-settings | `NeurUI/src/api/modules/memory-settings.ts` | `/memory-settings` | 7 |
| memory | `NeurUI/src/api/modules/memory.ts` | `/enhanced-memory-search`、`/memory`、`/memory-enhancement`、`/memory-share-groups`、`/memory-timeline`、`/semantic-search` | 101 |
| metacognition | `NeurUI/src/api/modules/metacognition.ts` | `/metacognition` | 7 |
| mobile | `NeurUI/src/api/modules/mobile.ts` | `/mobile` | 4 |
| model-adapter | `NeurUI/src/api/modules/model-adapter.ts` | `/model-adapter` | 3 |
| models | `NeurUI/src/api/modules/models.ts` | `/models` | 17 |
| negative-screen | `NeurUI/src/api/modules/negative-screen.ts` | `/negative-screen`、`/notifications` | 5 |
| neurflow | `NeurUI/src/api/modules/neurflow.ts` | `/neurflow` | 36 |
| notifications | `NeurUI/src/api/modules/notifications.ts` | `/notifications` | 6 |
| openplatform | `NeurUI/src/api/modules/openplatform.ts` | `/openplatform` | 8 |
| plans | `NeurUI/src/api/modules/plans.ts` | `/plans` | 6 |
| plugins | `NeurUI/src/api/modules/plugins.ts` | `/plugins` | 12 |
| projects | `NeurUI/src/api/modules/projects.ts` | `/projects` | 14 |
| providers | `NeurUI/src/api/modules/providers.ts` | `/providers` | 13 |
| rsiGovernance | `NeurUI/src/api/modules/rsiGovernance.ts` | `/governance` | 5 |
| rules | `NeurUI/src/api/modules/rules.ts` | `/rules` | 8 |
| runtime | `NeurUI/src/api/modules/runtime.ts` | `/runtime` | 4 |
| sandbox | `NeurUI/src/api/modules/sandbox.ts` | `/sandbox` | 6 |
| scheduler | `NeurUI/src/api/modules/scheduler.ts` | `/scheduler` | 7 |
| settings | `NeurUI/src/api/modules/settings.ts` | `/governance`、`/settings` | 17 |
| shared-config | `NeurUI/src/api/modules/shared-config.ts` | `/shared-config` | 14 |
| skill-pool | `NeurUI/src/api/modules/skill-pool.ts` | `/marketplace`、`/skill-pool` | 30 |
| sleep | `NeurUI/src/api/modules/sleep.ts` | `/sleep` | 10 |
| stats | `NeurUI/src/api/modules/stats.ts` | `/stats` | 7 |
| studio | `NeurUI/src/api/modules/studio.ts` | `/studio` | 20 |
| synonyms | `NeurUI/src/api/modules/synonyms.ts` | `/synonyms` | 10 |
| system-logs | `NeurUI/src/api/modules/system-logs.ts` | `/logs` | 2 |
| tasks | `NeurUI/src/api/modules/tasks.ts` | `/tasks` | 4 |
| teams | `NeurUI/src/api/modules/teams.ts` | `/teams` | 6 |
| text-evolution | `NeurUI/src/api/modules/text-evolution.ts` | `/evolution` | 10 |
| tool-layers | `NeurUI/src/api/modules/tool-layers.ts` | `/tool-layers` | 10 |
| trace | `NeurUI/src/api/modules/trace.ts` | `/trace` | 4 |
| webhooks | `NeurUI/src/api/modules/webhooks.ts` | `/webhooks` | 7 |

## 二、前端调用 ↔ 后端注册 差集

下列 **50** 处调用在本轮后端注册表里没有对应路由。这不等于「后端漏注册」——差异以显式列表暴露，由人去核；
**删条目不等于修好**（清单的价值在于可信，藏差异则整表不可信）。

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

## 三、后端已注册 ↔ 前端消费方 差集

下列 **20** 个后端一级前缀无任何前端客户端请求，属「后端已就位、前端待补消费方」的显式清单：

| 后端一级前缀 |
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
| `/skill-versions` |
| `/skills` |
| `/status` |
| `/sync` |
| `/tools` |
| `/user-groups` |
| `/workspace` |
<!-- API-INVENTORY:END -->
