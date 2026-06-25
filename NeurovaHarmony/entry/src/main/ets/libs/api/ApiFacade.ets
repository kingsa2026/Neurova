/**
 * ApiFacade - 统一 API 门面
 *
 * 职责：作为应用所有 API 调用的统一入口，聚合核心业务模块
 * 设计：门面模式，委托 HttpClient 执行请求；模块按业务域组织
 *
 * 用法：
 *   const api = ApiFacade.getInstance();
 *   const user = await api.auth.login(username, password);
 *   const agents = await api.agents.list();
 *   const mems = await api.memory.list('agent-1');
 *   const sys = await api.health.check();
 */

import { HttpClient } from './HttpClient';
import { AuthApi } from './modules/AuthApi';
import { AgentsApi } from './modules/AgentsApi';
import { SessionsApi } from './modules/SessionsApi';
import { MobilePairingApi } from './modules/MobilePairingApi';
import { ChatApi } from './modules/ChatApi';
import { MemoryApi } from './modules/MemoryApi';
import { KnowledgeApi } from './modules/KnowledgeApi';
import { ModelsApi } from './modules/ModelsApi';
import { HealthApi } from './modules/HealthApi';
import { SettingsApi } from './modules/SettingsApi';
import { AgentChannelsApi } from './modules/AgentChannelsApi';
import { CognitionApi } from './modules/CognitionApi';
import { CapabilityApi } from './modules/CapabilityApi';
import { RuntimeApi } from './modules/RuntimeApi';
import { PersonalityApi } from './modules/PersonalityApi';
import { CollaborationApi } from './modules/CollaborationApi';
import { MonitorApi } from './modules/MonitorApi';
import { ChannelIntegrationApi } from './modules/ChannelIntegrationApi';
import { SessionSyncApi } from './modules/SessionSyncApi';

export class ApiFacade {
  private static instance: ApiFacade;
  private client: HttpClient;

  // 业务模块（原有 5 个）
  public auth: AuthApi;
  public agents: AgentsApi;
  public sessions: SessionsApi;
  public mobilePairing: MobilePairingApi;
  public chat: ChatApi;

  // 业务模块（M3 新增 6 个）
  public memory: MemoryApi;
  public knowledge: KnowledgeApi;
  public models: ModelsApi;
  public health: HealthApi;
  public settings: SettingsApi;
  public agentChannels: AgentChannelsApi;

  // 业务模块（M4 新增 6 个）
  public cognition: CognitionApi;
  public capability: CapabilityApi;
  public runtime: RuntimeApi;
  public personality: PersonalityApi;
  public collaboration: CollaborationApi;
  public monitor: MonitorApi;
  // 业务模块（M4.6 新增 2 个 - 渠道系统）
  public channelIntegration: ChannelIntegrationApi;
  public sessionSync: SessionSyncApi;

  private constructor() {
    this.client = HttpClient.getInstance();
    // 原有模块
    this.auth = new AuthApi(this.client);
    this.agents = new AgentsApi(this.client);
    this.sessions = new SessionsApi(this.client);
    this.mobilePairing = new MobilePairingApi(this.client);
    this.chat = new ChatApi(this.client);
    // M3 新增模块
    this.memory = new MemoryApi(this.client);
    this.knowledge = new KnowledgeApi(this.client);
    this.models = new ModelsApi(this.client);
    this.health = new HealthApi(this.client);
    this.settings = new SettingsApi(this.client);
    this.agentChannels = new AgentChannelsApi(this.client);
    // M4 新增模块
    this.cognition = new CognitionApi(this.client);
    this.capability = new CapabilityApi(this.client);
    this.runtime = new RuntimeApi(this.client);
    this.personality = new PersonalityApi(this.client);
    this.collaboration = new CollaborationApi(this.client);
    this.monitor = new MonitorApi(this.client);
    // M4.6 新增模块（渠道系统）
    this.channelIntegration = new ChannelIntegrationApi(this.client);
    this.sessionSync = new SessionSyncApi(this.client);
  }

  static getInstance(): ApiFacade {
    if (!ApiFacade.instance) {
      ApiFacade.instance = new ApiFacade();
    }
    return ApiFacade.instance;
  }

  /** 获取底层 HttpClient（用于设置 baseUrl/token 等） */
  getClient(): HttpClient {
    return this.client;
  }
}
