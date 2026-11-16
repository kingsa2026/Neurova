/**
 * PageMap - 路由名 → 页面组件的**唯一**挂载点
 *
 * 此前 MainLayout 的 Navigation 未接 navDestination，Router.push 的页面名
 * 没有任何组件映射（内容区永远显示占位"加载中..."）——这是鸿蒙端路由的实际断点。
 * 本文件补上映射；未注册的页面名走 fallback 占位页。
 * M9.2：认知/能力/运行时/监控/协作/同步/渠道七域页面全部挂载。
 */

import { RouteNames } from './Router';
import { ShellPage } from '../pages/ShellPage';
import { LoginPage } from '../pages/LoginPage';
import { RegisterPage } from '../pages/RegisterPage';
import { DashboardPage } from '../pages/DashboardPage';
import { ChatPage } from '../pages/ChatPage';
import { PairingPage } from '../pages/PairingPage';
import { ConnectionPage } from '../pages/ConnectionPage';
import { AgentListPage } from '../pages/AgentListPage';
import { AgentFormPage } from '../pages/AgentFormPage';
import { AgentDetailPage } from '../pages/AgentDetailPage';
import { KnowledgeImportPage } from '../pages/KnowledgeImportPage';
import { EnterpriseSourcesPage } from '../pages/EnterpriseSourcesPage';
import { GraphPreviewPage } from '../pages/GraphPreviewPage';
import { AdminUsersPage } from '../pages/AdminUsersPage';
import { AdminGroupsPage } from '../pages/AdminGroupsPage';
import { AdminMarketPage } from '../pages/AdminMarketPage';
import { AdminSettingsPage } from '../pages/AdminSettingsPage';
import { KnowledgePage } from '../pages/KnowledgePage';
import { MemoryPage } from '../pages/MemoryPage';
import { ModelPage } from '../pages/ModelPage';
import { HealthPage } from '../pages/HealthPage';
import { SettingPage } from '../pages/SettingPage';
import { TaskPage } from '../pages/TaskPage';
import { FilePage } from '../pages/FilePage';
import { NotificationPage } from '../pages/NotificationPage';
import { AgentChannelPage } from '../pages/AgentChannelPage';
// M4 P2 认知层
import { ExperienceKnowledgePage } from '../pages/ExperienceKnowledgePage';
import { KnowledgeGraphPage } from '../pages/KnowledgeGraphPage';
import { MetacognitionPage } from '../pages/MetacognitionPage';
import { ReflectionPage } from '../pages/ReflectionPage';
import { GrowthPage } from '../pages/GrowthPage';
// M4 P2 能力层
import { AgentRulePage } from '../pages/AgentRulePage';
import { AgentFilePage } from '../pages/AgentFilePage';
import { AgentMediaPage } from '../pages/AgentMediaPage';
// M4 P2 运行时层
import { AgentSchedulerPage } from '../pages/AgentSchedulerPage';
import { ContextChannelPage } from '../pages/ContextChannelPage';
import { AgentComputerPage } from '../pages/AgentComputerPage';
import { AgentTracePage } from '../pages/AgentTracePage';
import { AgentTrajectoryPage } from '../pages/AgentTrajectoryPage';
import { SleepStatusPage } from '../pages/SleepStatusPage';
import { SleepSettingsPage } from '../pages/SleepSettingsPage';
import { AgentFirewallPage } from '../pages/AgentFirewallPage';
// M4 P2 监控与管理
import { StatsPage } from '../pages/StatsPage';
import { MonitorPage } from '../pages/MonitorPage';
import { LogPage } from '../pages/LogPage';
import { NeuronPage } from '../pages/NeuronPage';
// M4 P2 协作与工作流
import { CollaborationPage } from '../pages/CollaborationPage';
import { ProjectPage } from '../pages/ProjectPage';
import { TeamPage } from '../pages/TeamPage';
import { WorkflowPage } from '../pages/WorkflowPage';
// M5 P3 协作扩展
import { CollaborationTemplatePage } from '../pages/CollaborationTemplatePage';
import { CollaborationHistoryPage } from '../pages/CollaborationHistoryPage';
import { CollaborationInitiatePage } from '../pages/CollaborationInitiatePage';
import { WebhookPage } from '../pages/WebhookPage';
// M4.6 渠道系统
import { ChannelIntegrationPage } from '../pages/ChannelIntegrationPage';
import { SessionSyncPage } from '../pages/SessionSyncPage';
// P1-33 死页接线（M4 P2 知识技能扩展 + M5 P3 系统监控/用户扩展）
import { SkillPoolPage } from '../pages/SkillPoolPage';
import { AIGCPage } from '../pages/AIGCPage';
import { AuditPage } from '../pages/AuditPage';
import { BenchmarkPage } from '../pages/BenchmarkPage';
import { SandboxPage } from '../pages/SandboxPage';
import { FirewallPage } from '../pages/FirewallPage';
import { MarketplacePage } from '../pages/MarketplacePage';
import { GroupPage } from '../pages/GroupPage';
import { EnhancedUserPage } from '../pages/EnhancedUserPage';

@Builder
export function pageMap(name: string) {
  if (name === RouteNames.SHELL) {
    NavDestination() { ShellPage() }.hideTitleBar(true)
  } else if (name === RouteNames.LOGIN) {
    NavDestination() { LoginPage() }.hideTitleBar(true)
  } else if (name === RouteNames.REGISTER) {
    NavDestination() { RegisterPage() }.hideTitleBar(true)
  } else if (name === RouteNames.DASHBOARD) {
    NavDestination() { DashboardPage() }.hideTitleBar(true)
  } else if (name === RouteNames.CHAT) {
    NavDestination() { ChatPage() }.hideTitleBar(true)
  } else if (name === RouteNames.PAIRING) {
    NavDestination() { PairingPage() }.hideTitleBar(true)
  } else if (name === RouteNames.CONNECTION) {
    NavDestination() { ConnectionPage() }.hideTitleBar(true)
  } else if (name === RouteNames.AGENT_LIST) {
    NavDestination() { AgentListPage() }.hideTitleBar(true)
  } else if (name === RouteNames.AGENT_FORM) {
    NavDestination() { AgentFormPage() }.hideTitleBar(true)
  } else if (name === RouteNames.AGENT_DETAIL) {
    NavDestination() { AgentDetailPage() }.hideTitleBar(true)
  } else if (name === RouteNames.KNOWLEDGE_IMPORT) {
    NavDestination() { KnowledgeImportPage() }.hideTitleBar(true)
  } else if (name === RouteNames.ENTERPRISE_SOURCES) {
    NavDestination() { EnterpriseSourcesPage() }.hideTitleBar(true)
  } else if (name === RouteNames.GRAPH_PREVIEW) {
    NavDestination() { GraphPreviewPage() }.hideTitleBar(true)
  } else if (name === RouteNames.ADMIN_USERS) {
    NavDestination() { AdminUsersPage() }.hideTitleBar(true)
  } else if (name === RouteNames.ADMIN_GROUPS) {
    NavDestination() { AdminGroupsPage() }.hideTitleBar(true)
  } else if (name === RouteNames.ADMIN_MARKET) {
    NavDestination() { AdminMarketPage() }.hideTitleBar(true)
  } else if (name === RouteNames.ADMIN_SETTINGS) {
    NavDestination() { AdminSettingsPage() }.hideTitleBar(true)
  } else if (name === RouteNames.KNOWLEDGE) {
    NavDestination() { KnowledgePage() }.hideTitleBar(true)
  } else if (name === RouteNames.MEMORY) {
    NavDestination() { MemoryPage() }.hideTitleBar(true)
  } else if (name === RouteNames.MODEL) {
    NavDestination() { ModelPage() }.hideTitleBar(true)
  } else if (name === RouteNames.HEALTH) {
    NavDestination() { HealthPage() }.hideTitleBar(true)
  } else if (name === RouteNames.SETTINGS) {
    NavDestination() { SettingPage() }.hideTitleBar(true)
  } else if (name === RouteNames.TASK) {
    NavDestination() { TaskPage() }.hideTitleBar(true)
  } else if (name === RouteNames.FILE) {
    NavDestination() { FilePage() }.hideTitleBar(true)
  } else if (name === RouteNames.NOTIFICATION) {
    NavDestination() { NotificationPage() }.hideTitleBar(true)
  } else if (name === RouteNames.AGENT_CHANNEL) {
    NavDestination() { AgentChannelPage() }.hideTitleBar(true)
  } else if (name === RouteNames.EXPERIENCE_KNOWLEDGE) {
    NavDestination() { ExperienceKnowledgePage() }.hideTitleBar(true)
  } else if (name === RouteNames.KNOWLEDGE_GRAPH) {
    NavDestination() { KnowledgeGraphPage() }.hideTitleBar(true)
  } else if (name === RouteNames.METACOGNITION) {
    NavDestination() { MetacognitionPage() }.hideTitleBar(true)
  } else if (name === RouteNames.REFLECTION) {
    NavDestination() { ReflectionPage() }.hideTitleBar(true)
  } else if (name === RouteNames.GROWTH) {
    NavDestination() { GrowthPage() }.hideTitleBar(true)
  } else if (name === RouteNames.AGENT_RULE) {
    NavDestination() { AgentRulePage() }.hideTitleBar(true)
  } else if (name === RouteNames.AGENT_FILE) {
    NavDestination() { AgentFilePage() }.hideTitleBar(true)
  } else if (name === RouteNames.AGENT_MEDIA) {
    NavDestination() { AgentMediaPage() }.hideTitleBar(true)
  } else if (name === RouteNames.AGENT_SCHEDULER) {
    NavDestination() { AgentSchedulerPage() }.hideTitleBar(true)
  } else if (name === RouteNames.CONTEXT_CHANNEL) {
    NavDestination() { ContextChannelPage() }.hideTitleBar(true)
  } else if (name === RouteNames.AGENT_COMPUTER) {
    NavDestination() { AgentComputerPage() }.hideTitleBar(true)
  } else if (name === RouteNames.AGENT_TRACE) {
    NavDestination() { AgentTracePage() }.hideTitleBar(true)
  } else if (name === RouteNames.AGENT_TRAJECTORY) {
    NavDestination() { AgentTrajectoryPage() }.hideTitleBar(true)
  } else if (name === RouteNames.SLEEP_STATUS) {
    NavDestination() { SleepStatusPage() }.hideTitleBar(true)
  } else if (name === RouteNames.SLEEP_SETTINGS) {
    NavDestination() { SleepSettingsPage() }.hideTitleBar(true)
  } else if (name === RouteNames.AGENT_FIREWALL) {
    NavDestination() { AgentFirewallPage() }.hideTitleBar(true)
  } else if (name === RouteNames.STATS) {
    NavDestination() { StatsPage() }.hideTitleBar(true)
  } else if (name === RouteNames.MONITOR) {
    NavDestination() { MonitorPage() }.hideTitleBar(true)
  } else if (name === RouteNames.LOG) {
    NavDestination() { LogPage() }.hideTitleBar(true)
  } else if (name === RouteNames.NEURON) {
    NavDestination() { NeuronPage() }.hideTitleBar(true)
  } else if (name === RouteNames.COLLABORATION) {
    NavDestination() { CollaborationPage() }.hideTitleBar(true)
  } else if (name === RouteNames.PROJECT) {
    NavDestination() { ProjectPage() }.hideTitleBar(true)
  } else if (name === RouteNames.TEAM) {
    NavDestination() { TeamPage() }.hideTitleBar(true)
  } else if (name === RouteNames.WORKFLOW) {
    NavDestination() { WorkflowPage() }.hideTitleBar(true)
  } else if (name === RouteNames.COLLABORATION_TEMPLATE) {
    NavDestination() { CollaborationTemplatePage() }.hideTitleBar(true)
  } else if (name === RouteNames.COLLABORATION_HISTORY) {
    NavDestination() { CollaborationHistoryPage() }.hideTitleBar(true)
  } else if (name === RouteNames.COLLABORATION_INITIATE) {
    NavDestination() { CollaborationInitiatePage() }.hideTitleBar(true)
  } else if (name === RouteNames.WEBHOOK) {
    NavDestination() { WebhookPage() }.hideTitleBar(true)
  } else if (name === RouteNames.CHANNEL_INTEGRATION) {
    NavDestination() { ChannelIntegrationPage() }.hideTitleBar(true)
  } else if (name === RouteNames.SESSION_SYNC) {
    NavDestination() { SessionSyncPage() }.hideTitleBar(true)
  } else if (name === RouteNames.SKILL_POOL) {
    NavDestination() { SkillPoolPage() }.hideTitleBar(true)
  } else if (name === RouteNames.AIGC) {
    NavDestination() { AIGCPage() }.hideTitleBar(true)
  } else if (name === RouteNames.AUDIT) {
    NavDestination() { AuditPage() }.hideTitleBar(true)
  } else if (name === RouteNames.BENCHMARK) {
    NavDestination() { BenchmarkPage() }.hideTitleBar(true)
  } else if (name === RouteNames.SANDBOX) {
    NavDestination() { SandboxPage() }.hideTitleBar(true)
  } else if (name === RouteNames.FIREWALL) {
    NavDestination() { FirewallPage() }.hideTitleBar(true)
  } else if (name === RouteNames.MARKETPLACE) {
    NavDestination() { MarketplacePage() }.hideTitleBar(true)
  } else if (name === RouteNames.GROUP) {
    NavDestination() { GroupPage() }.hideTitleBar(true)
  } else if (name === RouteNames.ENHANCED_USER) {
    NavDestination() { EnhancedUserPage() }.hideTitleBar(true)
  } else {
    NavDestination() {
      Column() {
        Text('页面未注册').fontSize(16)
        Text(name).fontSize(12).opacity(0.6).margin({ top: 6 })
      }.width('100%').height('100%').justifyContent(FlexAlign.Center)
    }.hideTitleBar(false)
  }
}
