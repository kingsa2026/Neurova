# Neurova 浏览器控制台错误全面报告

**检查时间**: 2026-06-10 07:20-07:28  
**检查工具**: Chrome DevTools MCP  
**测试环境**: localhost:8100 (前端) / localhost:9527 (后端)  
**登录用户**: admin (角色: admin)

---

## 一、问题总览

| 类型 | 数量 | 严重程度 |
|------|------|----------|
| i18n 翻译键缺失 (Warning) | ~90条 | 低 |
| API 500 内部服务器错误 | 4个端点 | **高** |
| API 404 端点不存在 | 5个端点 | **高** |
| Vue 组件渲染错误 | 3个页面 | **中** |
| 未捕获 Promise 错误 | 3个页面 | **中** |
| Vue Prop 类型错误 | 1个页面 | **低** |

---

## 二、严重问题 (P0/P1) — API 端点 500 错误

### 2.1 Groups API — `list_groups()` 参数错误
- **页面**: `/groups`
- **端点**: `GET /api/v1/groups`
- **错误**: `"UserGroupManager.list_groups() got an unexpected keyword argument 'limit'"`
- **影响**: 用户组管理页面完全不可用
- **根因**: 后端 `list_groups()` 方法签名缺少 `limit` 参数
- **修复**: 检查 `neurova/auth/user_group_model.py` 的 `list_groups()` 方法

### 2.2 Collaboration Templates API — `list_projects` 属性缺失
- **页面**: `/collaboration`, `/collaboration/templates`, `/collaboration/initiate`
- **端点**: `GET /api/v1/collaboration/templates`
- **错误**: `"'CollaborationIsolationManager' object has no attribute 'list_projects'"`
- **影响**: 协作功能相关3个页面全部不可用
- **根因**: `CollaborationIsolationManager` 类缺少 `list_projects` 方法
- **修复**: 检查 `neurova/collaboration/collaboration_isolation.py`

### 2.3 Collaboration History API — 端点不存在
- **页面**: `/collaboration/history`
- **端点**: `GET /api/v1/collaboration/history`
- **错误**: `404 Not Found`
- **影响**: 协作历史页面不可用
- **根因**: 后端未实现 `/collaboration/history` 端点

---

## 三、严重问题 (P1) — API 端点 404 错误

### 3.1 Settings API — 端点不存在
- **页面**: `/settings`
- **端点**: `GET /api/v1/settings`
- **错误**: `404 Not Found`
- **影响**: 设置页面数据加载失败
- **修复**: 需要实现 `/api/v1/settings` 端点或移除前端调用

### 3.2 Sandbox API — 端点不存在
- **页面**: `/sandbox`
- **端点**: `GET /api/v1/sandbox`
- **错误**: `404 Not Found`
- **影响**: 沙箱页面数据加载失败

### 3.3 Benchmark API — 端点不存在
- **页面**: `/benchmark`
- **端点**: `GET /api/v1/benchmark/results`
- **错误**: `404 Not Found`
- **影响**: 基准测试页面数据加载失败

### 3.4 Memory Search Settings API — 端点不存在
- **页面**: `/memory/search-settings`
- **端点**: `GET /api/v1/memory-search/settings`
- **错误**: `404 Not Found`
- **影响**: 记忆搜索设置页面不可用

### 3.5 Chat Sessions API — 端点不存在
- **页面**: `/agent/:agentId/chat`
- **端点**: `GET /api/v1/chat/sessions?agent_id=default`
- **错误**: `404 Not Found`
- **影响**: 聊天会话列表加载失败

---

## 四、中等问题 (P2) — Vue 组件渲染错误

### 4.1 MonitorPage — AList Prop 类型错误
- **页面**: `/monitor`
- **错误**: `Invalid prop: type check failed for prop "dataSource". Expected Array, got Object`
- **影响**: 监控页面部分区域渲染失败
- **组件**: `GlassCard title="连接"` 内的 `AList`
- **修复**: 检查 `MonitorPage.vue` 中传递给 `AList` 的 `data-source` 数据类型

### 4.2 SessionSyncPage — 组件更新错误
- **页面**: `/session-sync`
- **错误**: `Unhandled error during execution of component update` + `Uncaught (in promise)`
- **影响**: 会话同步页面渲染异常

### 4.3 WorkflowPage — 组件更新错误
- **页面**: `/workflows`
- **错误**: `Unhandled error during execution of component update` + `Uncaught (in promise)`
- **影响**: 工作流页面渲染异常（间歇性）

---

## 五、低优先级问题 (P3) — i18n 翻译键缺失

### 5.1 按页面统计

| 页面 | 缺失键数 | 缺失的翻译键 |
|------|----------|-------------|
| `/skill-pool` | 9 | `nav.skillpool`, `skillPool.createSkill`, `skillPool.title`, `skillPool.publicSkills`, `skillPool.privateSkills`, `skillPool.searchPublic`, `skillPool.noPublic` |
| `/agents` | 2 | `nav.agentlist`, `agent.running` |
| `/tool-layers` | 1 | `nav.toollayers` |
| `/knowledge` | 13 | `knowledge.createItem`, `knowledge.importTitle`, `knowledge.searchPlaceholder`, `knowledge.filterCategory`, `knowledge.semanticSearch`, `knowledge.export`, `knowledge.import`, `knowledge.colTitle`, `knowledge.colCategory`, `knowledge.colContent`, `knowledge.colCreated`, `knowledge.colActions`, `knowledge.totalItems` |
| `/marketplace/skills` | 8 | `nav.skillmarket`, `market.featured`, `market.allSkills`, `market.title`, `market.searchPlaceholder`, `market.noSkills`, `market.install` |
| `/aigc` | 14 | `nav.aigc`, `aigc.title`, `aigc.text`, `aigc.image`, `aigc.audio`, `aigc.video`, `aigc.result`, `aigc.prompt`, `aigc.model`, `aigc.textPromptPlaceholder`, `aigc.selectModel`, `aigc.generate`, `aigc.noResult` |
| `/enhanced-users` | 1 | `nav.enhancedusers` |
| `/memory/search-settings` | 1 | `nav.memorysearchsettings` |
| `/session-sync` | 1 | `nav.sessionsync` |
| `/stats` | 1 | `nav.stats` |
| `/agent/:id/chat` | 1 | `nav.agentchat` |
| `/collaboration/templates` | 1 | `nav.collaborationtemplates` |
| `/collaboration/initiate` | 1 | `nav.collaborationinitiate` |
| `/collaboration/history` | 1 | `nav.collaborationhistory` |

### 5.2 翻译键分类

**导航键 (nav.*)** — 14个缺失:
```
nav.skillpool, nav.agentlist, nav.toollayers, nav.enhancedusers, 
nav.memorysearchsettings, nav.sessionsync, nav.stats, nav.agentchat,
nav.skillmarket, nav.aigc, nav.collaborationtemplates, 
nav.collaborationinitiate, nav.collaborationhistory
```

**页面功能键** — ~60个缺失:
- `skillPool.*` (6个)
- `knowledge.*` (12个)
- `market.*` (5个)
- `aigc.*` (12个)
- `agent.running` (1个)

---

## 六、页面健康状态总览

| 页面 | 状态 | 问题 |
|------|------|------|
| `/dashboard` | ✅ 正常 | - |
| `/models` | ✅ 正常 | - |
| `/analytics` | ✅ 正常 | - |
| `/health` | ✅ 正常 | - |
| `/logs` | ✅ 正常 | - |
| `/notifications` | ✅ 正常 | - |
| `/files` | ✅ 正常 | - |
| `/firewall` | ✅ 正常 | - |
| `/projects` | ✅ 正常 | - |
| `/teams` | ✅ 正常 | - |
| `/tasks` | ✅ 正常 | - |
| `/webhooks` | ✅ 正常 | - |
| `/audit` | ✅ 正常 | - |
| `/marketplace` | ✅ 正常 | - |
| `/agents` | ⚠️ Warning | 2条i18n警告 |
| `/skill-pool` | ⚠️ Warning | 9条i18n警告 |
| `/tool-layers` | ⚠️ Warning | 1条i18n警告 |
| `/knowledge` | ⚠️ Warning | 13条i18n警告 |
| `/marketplace/skills` | ⚠️ Warning | 10条i18n警告 |
| `/aigc` | ⚠️ Warning | 22条i18n警告 |
| `/stats` | ⚠️ Warning | 1条i18n警告 |
| `/enhanced-users` | ⚠️ Warning | 1条i18n警告 |
| `/memory/search-settings` | ❌ Error | i18n + API 404 |
| `/agent/default/chat` | ❌ Error | i18n + API 404 |
| `/monitor` | ❌ Error | Vue组件错误 + Promise错误 |
| `/session-sync` | ❌ Error | i18n + Vue组件错误 |
| `/workflows` | ⚠️ Warning | Vue组件错误（间歇性） |
| `/settings` | ❌ Error | API 404 |
| `/sandbox` | ❌ Error | API 404 |
| `/benchmark` | ❌ Error | API 404 |
| `/groups` | ❌ Error | **API 500** |
| `/collaboration` | ❌ Error | **API 500** |
| `/collaboration/templates` | ❌ Error | **API 500** |
| `/collaboration/initiate` | ❌ Error | **API 500** |
| `/collaboration/history` | ❌ Error | API 404 |

---

## 七、修复优先级建议

### 🔴 P0 — 立即修复 (影响核心功能)
1. **Groups API 500** — `UserGroupManager.list_groups()` 添加 `limit` 参数
2. **Collaboration API 500** — `CollaborationIsolationManager` 添加 `list_projects` 方法

### 🟠 P1 — 本迭代修复 (影响用户体验)
3. **MonitorPage Vue 错误** — 修复 `AList` 的 `dataSource` prop 类型
4. **SessionSyncPage Vue 错误** — 排查组件更新异常
5. **Settings API 404** — 实现端点或移除前端调用
6. **Chat Sessions API 404** — 实现端点
7. **Benchmark API 404** — 实现端点
8. **Sandbox API 404** — 实现端点

### 🟡 P2 — 下迭代修复 (翻译完整性)
9. **i18n 翻译键缺失** — 在 `zh.ts` 中添加 ~90个翻译键

---

## 八、测试后端 API 直接验证

```bash
# Groups API (应返回500)
curl -H "Authorization: Bearer $TOKEN" http://localhost:9527/api/v1/groups

# Collaboration Templates API (应返回500)  
curl -H "Authorization: Bearer $TOKEN" http://localhost:9527/api/v1/collaboration/templates

# Settings API (应返回404)
curl -H "Authorization: Bearer $TOKEN" http://localhost:9527/api/v1/settings

# Sandbox API (应返回404)
curl -H "Authorization: Bearer $TOKEN" http://localhost:9527/api/v1/sandbox
```

---

*报告生成于 2026-06-10 07:28*
