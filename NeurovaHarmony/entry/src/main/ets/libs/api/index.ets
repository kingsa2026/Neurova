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
