// Hypium 测试列表入口
import abilityTest from './Ability.test';
import configManagerTest from './ConfigManager.test';
import loggerTest from './Logger.test';
import errorManagerTest from './ErrorManager.test';
import eventBusTest from './EventBus.test';
import styleManagerTest from './StyleManager.test';
import animationManagerTest from './AnimationManager.test';
import layoutManagerTest from './LayoutManager.test';
import interactionManagerTest from './InteractionManager.test';
import messageManagerTest from './MessageManager.test';
import moduleManagerTest from './ModuleManager.test';
import chatPageTest from './ChatPage.test';
// 新增 API 模块测试套件
import memoryApiTest from './MemoryApi.test';
import knowledgeApiTest from './KnowledgeApi.test';
import modelsApiTest from './ModelsApi.test';
import healthApiTest from './HealthApi.test';
import settingsApiTest from './SettingsApi.test';
import agentChannelsApiTest from './AgentChannelsApi.test';
// M3 P1 页面测试套件
import registerPageTest from './RegisterPage.test';
import agentFormPageTest from './AgentFormPage.test';
import memoryPageTest from './MemoryPage.test';
import knowledgePageTest from './KnowledgePage.test';
import modelPageTest from './ModelPage.test';
import healthPageTest from './HealthPage.test';
import settingPageTest from './SettingPage.test';
import agentChannelPageTest from './AgentChannelPage.test';
// M4 P2 API 模块测试套件
import cognitionApiTest from './CognitionApi.test';
import capabilityApiTest from './CapabilityApi.test';
import runtimeApiTest from './RuntimeApi.test';
import personalityApiTest from './PersonalityApi.test';
import collaborationApiTest from './CollaborationApi.test';
import monitorApiTest from './MonitorApi.test';
// M4.6 P2 渠道系统 API 模块测试套件
import channelIntegrationApiTest from './ChannelIntegrationApi.test';
import sessionSyncApiTest from './SessionSyncApi.test';
// M4 P2 认知层页面测试套件
import experienceKnowledgePageTest from './ExperienceKnowledgePage.test';
import knowledgeGraphPageTest from './KnowledgeGraphPage.test';
import metacognitionPageTest from './MetacognitionPage.test';
import reflectionPageTest from './ReflectionPage.test';
import growthPageTest from './GrowthPage.test';
// M4 P2 能力 + 个性页面测试套件
import agentRulePageTest from './AgentRulePage.test';
import agentFilePageTest from './AgentFilePage.test';
import agentMediaPageTest from './AgentMediaPage.test';
import agentEmotionPageTest from './AgentEmotionPage.test';
import agentPersonalityPageTest from './AgentPersonalityPage.test';
// M4 P2 运行时层页面测试套件
import agentSchedulerPageTest from './AgentSchedulerPage.test';
import contextChannelPageTest from './ContextChannelPage.test';
import agentComputerPageTest from './AgentComputerPage.test';
import agentTracePageTest from './AgentTracePage.test';
import agentTrajectoryPageTest from './AgentTrajectoryPage.test';
import sleepStatusPageTest from './SleepStatusPage.test';
import sleepSettingsPageTest from './SleepSettingsPage.test';
import agentFirewallPageTest from './AgentFirewallPage.test';
// M4 P2 知识技能扩展页面测试套件
import skillPoolPageTest from './SkillPoolPage.test';
import skillMarketPageTest from './SkillMarketPage.test';
import aigcPageTest from './AIGCPage.test';
import toolLayerPageTest from './ToolLayerPage.test';
// M4 P2 协作与工作流页面测试套件
import workflowPageTest from './WorkflowPage.test';
import collaborationPageTest from './CollaborationPage.test';
import projectPageTest from './ProjectPage.test';
import teamPageTest from './TeamPage.test';
import taskPageTest from './TaskPage.test';
// M4.6 P2 渠道系统页面测试套件
import channelIntegrationPageTest from './ChannelIntegrationPage.test';
import sessionSyncPageTest from './SessionSyncPage.test';
// M4.6 P2 监控与管理页面测试套件
import statsPageTest from './StatsPage.test';
import monitorPageTest from './MonitorPage.test';
import logPageTest from './LogPage.test';
import filePageTest from './FilePage.test';
import notificationPageTest from './NotificationPage.test';
import neuronPageTest from './NeuronPage.test';
// M5 P3 协作扩展与市场页面测试套件
import collaborationTemplatePageTest from './CollaborationTemplatePage.test';
import collaborationHistoryPageTest from './CollaborationHistoryPage.test';
import collaborationInitiatePageTest from './CollaborationInitiatePage.test';
import webhookPageTest from './WebhookPage.test';
import marketplacePageTest from './MarketplacePage.test';
// M5 P3 系统监控扩展页面测试套件
import auditPageTest from './AuditPage.test';
import benchmarkPageTest from './BenchmarkPage.test';
import sandboxPageTest from './SandboxPage.test';
import firewallPageTest from './FirewallPage.test';
import analyticsPageTest from './AnalyticsPage.test';
// M5 P3 用户与记忆扩展页面测试套件
import groupPageTest from './GroupPage.test';
import enhancedUserPageTest from './EnhancedUserPage.test';
import agentSkillPageTest from './AgentSkillPage.test';
import memorySettingsPageTest from './MemorySettingsPage.test';
import memorySearchSettingsPageTest from './MemorySearchSettingsPage.test';
// M5.2 性能优化测试套件
import chunkBatcherTest from './ChunkBatcher.test';
import simpleDataSourceTest from './SimpleDataSource.test';

export default function testsuite() {
  abilityTest();
  configManagerTest();
  loggerTest();
  errorManagerTest();
  eventBusTest();
  styleManagerTest();
  animationManagerTest();
  layoutManagerTest();
  interactionManagerTest();
  messageManagerTest();
  moduleManagerTest();
  chatPageTest();
  // 新增 API 模块测试套件
  memoryApiTest();
  knowledgeApiTest();
  modelsApiTest();
  healthApiTest();
  settingsApiTest();
  agentChannelsApiTest();
  // M3 P1 页面测试套件
  registerPageTest();
  agentFormPageTest();
  memoryPageTest();
  knowledgePageTest();
  modelPageTest();
  healthPageTest();
  settingPageTest();
  agentChannelPageTest();
  // M4 P2 API 模块测试套件
  cognitionApiTest();
  capabilityApiTest();
  runtimeApiTest();
  personalityApiTest();
  collaborationApiTest();
  monitorApiTest();
  // M4.6 P2 渠道系统 API 模块测试套件
  channelIntegrationApiTest();
  sessionSyncApiTest();
  // M4 P2 认知层页面测试套件
  experienceKnowledgePageTest();
  knowledgeGraphPageTest();
  metacognitionPageTest();
  reflectionPageTest();
  growthPageTest();
  // M4 P2 能力 + 个性页面测试套件
  agentRulePageTest();
  agentFilePageTest();
  agentMediaPageTest();
  agentEmotionPageTest();
  agentPersonalityPageTest();
  // M4 P2 运行时层页面测试套件
  agentSchedulerPageTest();
  contextChannelPageTest();
  agentComputerPageTest();
  agentTracePageTest();
  agentTrajectoryPageTest();
  sleepStatusPageTest();
  sleepSettingsPageTest();
  agentFirewallPageTest();
  // M4 P2 知识技能扩展页面测试套件
  skillPoolPageTest();
  skillMarketPageTest();
  aigcPageTest();
  toolLayerPageTest();
  // M4 P2 协作与工作流页面测试套件
  workflowPageTest();
  collaborationPageTest();
  projectPageTest();
  teamPageTest();
  taskPageTest();
  // M4.6 P2 渠道系统页面测试套件
  channelIntegrationPageTest();
  sessionSyncPageTest();
  // M4.6 P2 监控与管理页面测试套件
  statsPageTest();
  monitorPageTest();
  logPageTest();
  filePageTest();
  notificationPageTest();
  neuronPageTest();
  // M5 P3 协作扩展与市场页面测试套件
  collaborationTemplatePageTest();
  collaborationHistoryPageTest();
  collaborationInitiatePageTest();
  webhookPageTest();
  marketplacePageTest();
  // M5 P3 系统监控扩展页面测试套件
  auditPageTest();
  benchmarkPageTest();
  sandboxPageTest();
  firewallPageTest();
  analyticsPageTest();
  // M5 P3 用户与记忆扩展页面测试套件
  groupPageTest();
  enhancedUserPageTest();
  agentSkillPageTest();
  memorySettingsPageTest();
  memorySearchSettingsPageTest();
  // M5.2 性能优化测试套件
  chunkBatcherTest();
  simpleDataSourceTest();
}
