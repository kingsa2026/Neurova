# 文件删除差异报告

## 概述
从提交 `d56b0d4`（2026-06-03 16:51）到当前版本（`7db6250`），共有 **204 个文件被删除**，总计删除 **47,344 行代码**。

## 删除文件统计

### 按目录分类

#### 1. neuUI/src/components/ (21个文件)
- AgentSidebar (345行)
- AgentSidebarPanel (359行)
- AppHeader (214行)
- AppLayout (31行)
- AppSidebar (102行)
- BrainwaveVisualizer (448行)
- ConfirmModal (75行)
- DataTable (102行)
- FileUploader (138行)
- FormDrawer (82行)
- LiquidGlas (139行)
- LiquidGlass (185行)
- LiquidGlassPorte (72行)
- LiquidGlassSimple (106行)
- MemoryTimeline (287行)
- MobilePairingPanel (346行)
- PageHeader (43行)
- StarBackground (349行)
- StatCard (49行)
- StreamingChat (349行)

#### 2. neuUI/src/pages/ (61个文件)
- AIGCPage (32行)
- AgentChannelPage (375行)
- AgentComputerPage (65行)
- AgentEmotionPage (283行)
- AgentFilePage (92行)
- AgentFirewallPage (509行)
- AgentFormPage (414行)
- AgentListPage (93行)
- AgentMediaPage (152行)
- AgentPersonalityPage (98行)
- AgentRulePage (66行)
- AgentSchedulerPage (77行)
- AgentSkillPage (72行)
- AgentSleepPage (123行)
- AgentTracePage (51行)
- AgentTrajectoryPage (46行)
- AnalyticsPage (379行)
- AuditPage (491行)
- BenchmarkPage (75行)
- ChatPage (未知)
- CollaborationHistoryPage (未知)
- CollaborationInitiatePage (未知)
- CollaborationPage (未知)
- CollaborationTemplatePage (未知)
- ContextChannelPage (未知)
- DashboardPage (未知)
- EnhancedUserPage (未知)
- ExperienceKnowledgePage (未知)
- FilePage (未知)
- FirewallPage (未知)
- GroupPage (未知)
- GrowthPage (未知)
- HealthPage (未知)
- KnowledgeGraphPage (未知)
- KnowledgePage (未知)
- LogPage (未知)
- LoginPage (未知)
- MarketplacePage (未知)
- MemoryPage (未知)
- MemorySearchSettingsPage (未知)
- MetacognitionPage (未知)
- ModelPage (未知)
- MonitorPage (未知)
- NotificationPage (未知)
- PlaceholderPage (未知)
- ProjectPage (未知)
- ReflectionPage (未知)
- RegisterPage (未知)
- SandboxPage (未知)
- SecurityPage (未知)
- SettingPage (未知)
- SkillMarketPage (未知)
- SkillPoolPage (未知)
- SleepSettingsPage (未知)
- SleepStatusPage (未知)
- StatsPage (未知)
- TaskPage (未知)
- TeamPage (未知)
- ToolLayerPage (未知)
- WebhookPage (未知)
- WorkflowPage (未知)

#### 3. neuUI/src/composables/ (3个文件)
- useAgentPag (86行)
- usePaginatio (63行)
- useStreamCha (133行)

#### 4. neuUI/src/layouts/ (1个文件)
- MainLayout (200行)

#### 5. neuUI/src/services/ (2个文件)
- errorLogge (109行)
- errorReportin (77行)

#### 6. neuUI/src/src/ (重复目录结构，102个文件)
- 包含 components/, pages/, composables/, layouts/, services/, stores/, utils/, views/ 等子目录
- 这些文件与上级目录中的文件内容相同，可能是重复的目录结构

#### 7. neurova/ 后端文件 (4个文件)
- neurova/agent/config.py (154行)
- neurova/agent/scheduler.py (1138行)
- neurova/context.py (0行，空文件)
- neurova/context_legacy.py (1393行)

## 关键发现

### 1. 重复目录结构
发现 `neuUI/src/src/` 目录包含与 `neuUI/src/` 相同的文件结构，这可能是由于：
- 误操作创建了重复目录
- 版本控制问题导致文件被复制
- 清理重复文件时删除了错误的版本

### 2. 核心前端文件删除
删除的组件和页面包括：
- **核心布局**: AppLayout, MainLayout
- **聊天功能**: ChatPage, StreamingChat
- **Agent管理**: AgentListPage, AgentFormPage, AgentFirewallPage
- **记忆系统**: MemoryPage, MemoryTimeline
- **模型管理**: ModelPage
- **安全系统**: SecurityPage, FirewallPage

### 3. 后端文件删除
- `neurova/agent/scheduler.py` (1138行) - 任务调度器
- `neurova/agent/config.py` (154行) - Agent配置
- `neurova/context_legacy.py` (1393行) - 旧版上下文管理器

## 影响分析

### 前端功能影响
1. **UI组件缺失**: 所有自定义组件被删除，可能影响界面显示
2. **页面路由缺失**: 所有页面组件被删除，导致路由无法加载
3. **状态管理缺失**: Pinia stores 被删除，影响状态管理
4. **API客户端缺失**: API模块被删除，影响与后端通信

### 后端功能影响
1. **任务调度缺失**: scheduler.py 被删除，影响定时任务
2. **配置管理缺失**: config.py 被删除，影响Agent配置
3. **上下文管理降级**: 旧版上下文管理器被删除，但新版可能已存在

## 恢复建议

### 优先恢复项目
1. **核心UI组件**: AppLayout, MainLayout, ChatPage
2. **Agent管理页面**: AgentListPage, AgentFormPage
3. **API客户端**: chat.ts, agents.ts
4. **后端调度器**: scheduler.py

### 恢复方法
1. **使用git restore恢复特定文件**:
   ```bash
   git restore d56b0d4 -- neuUI/src/pages/ChatPage.vue
   ```

2. **恢复整个目录**:
   ```bash
   git restore d56b0d4 -- neuUI/src/components/
   ```

3. **从备份恢复**:
   - 检查 `backup_neuUI_full.zip` 是否包含完整文件

## 结论

本次删除操作影响了项目的前端UI和部分后端功能。建议根据业务需求选择性恢复关键文件，特别是：
1. 核心页面和组件
2. API客户端模块
3. 后端调度和配置文件

**报告生成时间**: 2026-06-04 00:20
**对比基准提交**: d56b0d4 (2026-06-03 16:51)
**当前提交**: 7db6250 (2026-06-03 19:57)