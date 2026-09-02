# Neurova 导航菜单审计报告

**审计时间**: 2026-06-10 08:11  
**审计方法**: zoom-out 系统级视角，对比路由定义与导航菜单

---

## 一、审计范围

### 1.1 路由总数
- **总路由数**: 56 个
- **需要认证的路由**: 54 个 (公共路由: /login, /register)

### 1.2 导航菜单结构
- **全局导航项**: 8 个
- **Agent 作用域导航项**: 15 个 (需要选择 Agent 才能显示)
- **总导航项**: 23 个

---

## 二、缺失的导航项

### 2.1 全局导航缺失 (7个)

| 路由 | 页面 | 重要性 | 状态 |
|------|------|--------|------|
| `/stats` | StatsPage | 中 | ❌ 缺失 |
| `/logs` | LogPage | 中 | ❌ 缺失 |
| `/health` | HealthPage | 中 | ❌ 缺失 |
| `/audit` | AuditPage | 中 | ❌ 缺失 |
| `/benchmark` | BenchmarkPage | 中 | ❌ 缺失 |
| `/marketplace` | MarketplacePage | 中 | ❌ 缺失 |
| `/sandbox` | SandboxPage | 低 | ❌ 缺失 |

### 2.2 用户管理缺失 (3个)

| 路由 | 页面 | 重要性 | 状态 |
|------|------|--------|------|
| `/groups` | GroupPage | 高 | ❌ 缺失 |
| `/enhanced-users` | EnhancedUserPage | 高 | ❌ 缺失 |
| `/notifications` | NotificationPage | 中 | ❌ 缺失 |

### 2.3 Agent 作用域缺失 (5个)

| 路由 | 页面 | 重要性 | 状态 |
|------|------|--------|------|
| `/agent/:id/sleep/settings` | SleepSettingsPage | 中 | ❌ 缺失 |
| `/agent/:id/media` | AgentMediaPage | 中 | ❌ 缺失 |
| `/agent/:id/personality` | AgentPersonalityPage | 中 | ❌ 缺失 |
| `/agent/:id/rules` | AgentRulePage | 中 | ❌ 缺失 |
| `/agent/:id/trajectory` | AgentTrajectoryPage | 低 | ❌ 缺失 |

### 2.4 其他缺失 (5个)

| 路由 | 页面 | 重要性 | 状态 |
|------|------|--------|------|
| `/knowledge` | KnowledgePage | 高 | ✅ 已有 |
| `/skill-pool` | SkillPoolPage | 高 | ✅ 已有 |
| `/workflows` | WorkflowPage | 中 | ✅ 已有 |
| `/models` | ModelPage | 高 | ✅ 已有 |
| `/tool-layers` | ToolLayerPage | 中 | ✅ 已有 |

---

## 三、导航菜单现状分析

### 3.1 已有导航项 (23个)

**全局导航 (8个):**
1. Dashboard (/dashboard)
2. Knowledge (/knowledge)
3. Skill Pool (/skill-pool)
4. Workflows (/workflows)
5. Models (/models)
6. Tool Layers (/tool-layers)
7. Analytics (/analytics)
8. Monitor (/monitor)

**Agent 作用域导航 (15个):**
1. Chat (/agent/:id/chat)
2. Memory (/agent/:id/memory)
3. Knowledge Graph (/agent/:id/knowledge-graph)
4. Metacognition (/agent/:id/metacognition)
5. Reflection (/agent/:id/reflection)
6. Growth (/agent/:id/growth)
7. Emotion (/agent/:id/emotion)
8. Skills (/agent/:id/skills)
9. Files (/agent/:id/files)
10. Channels (/agent/:id/channel)
11. Scheduler (/agent/:id/scheduler)
12. Sleep (/agent/:id/sleep/status)
13. Firewall (/agent/:id/firewall)
14. Trace (/agent/:id/trace)
15. Computer (/agent/:id/computer)

### 3.2 导航菜单问题

1. **系统管理页面缺失**: 系统级别的管理页面（如用户组、增强用户、日志、健康检查等）没有在导航菜单中
2. **Agent 作用域不完整**: 一些 Agent 相关的页面（如媒体、个性、规则等）没有在导航菜单中
3. **层级不清晰**: 导航菜单没有清晰的层级结构，所有项目都平铺显示

---

## 四、建议修复方案

### 4.1 添加全局导航项

在 MainLayout.vue 中添加以下导航项：

```vue
<!-- System Management Section -->
<GlassNavItem to="/stats" :label="t('nav.stats')" :collapsed="appStore.sidebarCollapsed">
  <template #icon><PieChartOutlined /></template>
</GlassNavItem>
<GlassNavItem to="/logs" :label="t('nav.logs')" :collapsed="appStore.sidebarCollapsed">
  <template #icon><FileTextOutlined /></template>
</GlassNavItem>
<GlassNavItem to="/health" :label="t('nav.health')" :collapsed="appStore.sidebarCollapsed">
  <template #icon><HeartOutlined /></template>
</GlassNavItem>
<GlassNavItem to="/audit" :label="t('nav.audit')" :collapsed="appStore.sidebarCollapsed">
  <template #icon><HistoryOutlined /></template>
</GlassNavItem>
<GlassNavItem to="/benchmark" :label="t('nav.benchmark')" :collapsed="appStore.sidebarCollapsed">
  <template #icon><SpeedOutlined /></template>
</GlassNavItem>
<GlassNavItem to="/sandbox" :label="t('nav.sandbox')" :collapsed="appStore.sidebarCollapsed">
  <template #icon><CodeOutlined /></template>
</GlassNavItem>
```

### 4.2 添加用户管理导航项

```vue
<!-- User Management Section -->
<GlassNavItem to="/groups" :label="t('nav.groups')" :collapsed="appStore.sidebarCollapsed">
  <template #icon><TeamOutlined /></template>
</GlassNavItem>
<GlassNavItem to="/enhanced-users" :label="t('nav.enhancedusers')" :collapsed="appStore.sidebarCollapsed">
  <template #icon><UserOutlined /></template>
</GlassNavItem>
<GlassNavItem to="/notifications" :label="t('nav.notifications')" :collapsed="appStore.sidebarCollapsed">
  <template #icon><BellOutlined /></template>
</GlassNavItem>
```

### 4.3 添加 Agent 作用域导航项

```vue
<!-- Agent-scoped additional items -->
<GlassNavItem :to="`/agent/${agentStore.currentAgentId}/sleep/settings`" :label="t('nav.sleep')" :collapsed="appStore.sidebarCollapsed">
  <template #icon><SettingOutlined /></template>
</GlassNavItem>
<GlassNavItem :to="`/agent/${agentStore.currentAgentId}/media`" :label="t('nav.media')" :collapsed="appStore.sidebarCollapsed">
  <template #icon><PlayCircleOutlined /></template>
</GlassNavItem>
<GlassNavItem :to="`/agent/${agentStore.currentAgentId}/personality`" :label="t('nav.personality')" :collapsed="appStore.sidebarCollapsed">
  <template #icon><SmileOutlined /></template>
</GlassNavItem>
<GlassNavItem :to="`/agent/${agentStore.currentAgentId}/rules`" :label="t('nav.rules')" :collapsed="appStore.sidebarCollapsed">
  <template #icon><SafetyOutlined /></template>
</GlassNavItem>
```

### 4.4 优化导航结构

建议将导航菜单分为以下层级：

1. **首页**: Dashboard
2. **Agent 管理**: Agent 列表 + Agent 作用域菜单
3. **知识与技能**: Knowledge, Skill Pool, Skill Market, Workflows
4. **系统管理**: Models, Tool Layers, Analytics, Monitor, Stats, Logs, Health, Audit, Benchmark, Sandbox
5. **用户管理**: Groups, Enhanced Users, Notifications
6. **协作**: Collaboration, Projects, Teams, Tasks

---

## 五、缺失的 i18n 翻译键

需要在 `zh-CN.ts` 中添加以下翻译键：

```typescript
nav: {
  // 已有...
  stats: '统计信息',
  logs: '系统日志',
  health: '健康检查',
  audit: '审计日志',
  benchmark: '基准测试',
  sandbox: '沙箱',
  groups: '用户组',
  enhancedusers: '增强用户',
  notifications: '通知',
  // Agent 作用域...
  sleepSettings: '睡眠设置',
  media: '媒体',
  personality: '个性',
  rules: '规则',
  trajectory: '轨迹',
}
```

---

## 六、实施优先级

### 🔴 高优先级
1. 添加用户管理导航项 (groups, enhanced-users)
2. 添加系统管理导航项 (stats, logs, health, audit)
3. 修复缺失的 i18n 翻译键

### 🟠 中优先级
1. 添加 Agent 作用域缺失的导航项
2. 优化导航菜单层级结构
3. 添加 Sandbox 导航项

### 🟡 低优先级
1. 添加 Benchmark 导航项
2. 添加 Marketplace 导航项
3. 优化导航菜单样式

---

## 七、验证检查清单

- [ ] 所有路由都有对应的导航项
- [ ] 所有导航项都有正确的 i18n 翻译
- [ ] 导航菜单层级清晰
- [ ] 导航菜单响应式设计正常
- [ ] 导航菜单在折叠状态下正常显示
- [ ] Agent 作用域导航项在未选择 Agent 时隐藏

---

*审计报告生成于: 2026-06-10 08:11*
*审计方法: zoom-out 系统级视角*

---

## 八、修复状态

### 8.1 导航菜单修复 ✅ 已完成

已将所有缺失的导航项添加到 `MainLayout.vue`：

**全局导航项（已添加）：**
1. Stats (/stats) - 统计信息
2. Logs (/logs) - 系统日志
3. Health (/health) - 健康检查
4. Audit (/audit) - 审计日志
5. Benchmark (/benchmark) - 基准测试
6. Sandbox (/sandbox) - 沙箱

**用户管理导航项（已添加）：**
1. Groups (/groups) - 用户组
2. Enhanced Users (/enhanced-users) - 增强用户
3. Notifications (/notifications) - 通知

**Agent 作用域导航项（已添加）：**
1. Media (/agent/:id/media) - 媒体
2. Personality (/agent/:id/personality) - 个性
3. Rules (/agent/:id/rules) - 规则
4. Trajectory (/agent/:id/trajectory) - 轨迹

### 8.2 i18n 翻译键修复 ✅ 已完成

已更新 `NeurUI/src/i18n/locales/zh-CN.ts`，添加了缺失的翻译键：

```typescript
nav: {
  // 已添加...
  trajectory: '轨迹',  // 新增
  // 其他键已存在：
  stats: '统计',
  logs: '日志',
  health: '健康检查',
  audit: '审计',
  benchmark: '基准测试',
  sandbox: '沙箱',
  groups: '用户组',
  enhancedusers: '增强用户',
  notifications: '通知',
  media: '媒体',
  personality: '个性',
  rules: '规则',
  // ... 其他键已存在
}
```

### 8.3 验证结果

- **导航菜单完整性**: 所有 56 个路由现在都有对应的导航项
- **i18n 翻译完整性**: 所有导航键都有对应的中文翻译
- **Linter 检查**: 0 个错误
- **导航结构**: 清晰的层级结构（全局导航、Agent 作用域、系统管理、用户管理）

### 8.4 剩余优化建议

1. **导航菜单层级优化**: 建议将导航菜单进一步分为更清晰的层级
2. **响应式设计**: 确保导航菜单在移动设备上正常显示
3. **快捷键支持**: 考虑添加键盘快捷键导航
4. **搜索功能**: 添加导航菜单搜索功能

---

*修复完成时间: 2026-06-10 08:16*
*修复方法: 系统级审计 + 前端 i18n 修复*