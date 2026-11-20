// api 库统一导出
// 原有模块
export { HttpClient, HttpBackend, HttpInterceptor, RequestOptions } from './HttpClient';
export { ApiFacade } from './ApiFacade';
export { AuthApi } from './modules/AuthApi';
export { AgentsApi } from './modules/AgentsApi';
export { SessionsApi } from './modules/SessionsApi';
export { MobilePairingApi } from './modules/MobilePairingApi';
export { ChatApi } from './modules/ChatApi';
// M3 新增模块
export { MemoryApi, MemorySearchQuery } from './modules/MemoryApi';
export { KnowledgeApi, KnowledgeSearchRequest } from './modules/KnowledgeApi';
export { ModelsApi } from './modules/ModelsApi';
export { HealthApi } from './modules/HealthApi';
export { SettingsApi, SettingUpdateBody, SettingResetBody } from './modules/SettingsApi';
export { AgentChannelsApi, ChannelTestResult, ChannelToggleBody } from './modules/AgentChannelsApi';
// M4 新增模块
export { CognitionApi } from './modules/CognitionApi';
export { CapabilityApi } from './modules/CapabilityApi';
export { RuntimeApi } from './modules/RuntimeApi';
export { PersonalityApi } from './modules/PersonalityApi';
export { CollaborationApi } from './modules/CollaborationApi';
export { MonitorApi } from './modules/MonitorApi';
// M4.6 新增模块（渠道系统）
export { ChannelIntegrationApi } from './modules/ChannelIntegrationApi';
export { SessionSyncApi } from './modules/SessionSyncApi';
// M5a 新增模块（AIGC 生成域）
export { AigcApi } from './modules/AigcApi';
// P1-34 新增模块（Webhook 管理域）
export { WebhookApi, WebhookInfoDto, WebhookUpsertBody, WebhookUpdateBody } from './modules/WebhookApi';
// R6 新增模块（技能/审计/基准/市场/沙盒五域，P1-33 移交接线）
export { SkillsApi, SkillInfoDto } from './modules/SkillsApi';
export { AuditApi, AuditRecordDto, AuditPageDto, AuditPageStatsDto, AuditSearchHitDto, AuditStatsDto, AuditListParams, AuditSearchBody } from './modules/AuditApi';
export { BenchmarkApi, BenchmarkSuiteDto, BenchmarkRunDto, BenchmarkRunsPageDto, BenchmarkRunBody } from './modules/BenchmarkApi';
export { MarketplaceApi, MarketSkillDto, MarketSkillPageDto, MarketListParams, MarketInstallBody } from './modules/MarketplaceApi';
export { SandboxApi, SandboxViewDto, SandboxStartBody, SandboxExecDto } from './modules/SandboxApi';
// 车道F 新增模块（蜂群协作过程视图：协作图/候选板读面，对齐 PC console.ts）
export { ConsoleApi } from './modules/ConsoleApi';
export { SwarmGraphResult, SwarmGraphNode, SwarmGraphEdge, SwarmGraphMeta, CandidateBoardResult, CandidateEntry } from './modules/ConsoleApi';
