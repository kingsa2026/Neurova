/**
 * types - 统一类型库
 *
 * 职责：集中定义所有共享类型（接口、枚举、类型别名）
 * 设计：纯类型文件，无运行时逻辑，零依赖
 *
 * 用法：
 *   import { ApiResponse, User, WSMessage } from '../libs/types';
 */

// ===========================================================================
// 1. 通用 API 信封
// ===========================================================================

/** 后端统一响应格式 { code, message, data } */
export interface ApiResponse<T = Object> {
  code: number;          // 0=成功，非 0=错误
  message: string;
  data: T;
}

/** 分页查询参数（page/size 模式） */
export interface PageParams {
  page?: number;
  size?: number;
}

/** 分页结果 */
export interface PageResult<T> {
  items: T[];
  total: number;
  page: number;
  size: number;
  pages?: number;
}

/** 错误响应体 */
export interface ErrorBody {
  code: string;          // 错误码字符串，如 "auth_failed"
  message: string;       // 用户可见错误消息
  details?: Object;      // 可选的额外上下文
}

/** 通用元数据 */
export type Metadata = Record<string, Object>;

// ===========================================================================
// 2. 用户与鉴权
// ===========================================================================

export type UserRole = 'admin' | 'user' | 'viewer';
export type UserStatus = 'active' | 'inactive' | 'banned';

export interface User {
  id: string;
  username: string;
  email: string;
  role: UserRole;
  status: UserStatus;
  avatar?: string;
  createdAt?: string;
}

export interface LoginForm {
  username: string;
  password: string;
  remember?: boolean;
}

export interface AuthTokens {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

// ===========================================================================
// 3. Agent 与会话
// ===========================================================================

export type AgentStatus = 'active' | 'inactive' | 'sleeping' | 'error';

export interface AgentConfig {
  systemPrompt?: string;
  temperature?: number;
  maxTokens?: number;
  topP?: number;
  ttsEnabled?: boolean;
  ttsVoice?: string;
  ttsSpeed?: number;
  ttsPitch?: number;
  tools?: string[];
  skills?: string[];
}

export interface AgentStats {
  totalConversations: number;
  totalMessages: number;
  totalTokens: number;
  avgResponseTime: number;
  lastActiveAt?: string;
}

export interface Agent {
  id: string;
  name: string;
  description?: string;
  model?: string;
  provider?: string;
  status: AgentStatus;
  avatar?: string;
  createdAt: string;
  updatedAt: string;
  config?: AgentConfig;
  stats?: AgentStats;
}

export interface Session {
  id: string;
  title: string;
  agentId: string;
  createdAt: string;
  updatedAt: string;
  messageCount: number;
}

// ===========================================================================
// 4. 消息与附件
// ===========================================================================

export type MessageRole = 'user' | 'assistant' | 'system';
export type AttachmentType = 'image' | 'document' | 'audio' | 'video' | 'file';
export type ToolCallStatus = 'calling' | 'done' | 'error';

export interface ChatAttachment {
  id: string;
  name: string;
  type: AttachmentType;
  url: string;
  size: number;
  mimeType?: string;
}

export interface ToolCallInfo {
  id: string;
  name: string;
  arguments: Record<string, Object>;
  status: ToolCallStatus;
}

export interface ToolResultInfo {
  toolCallId: string;
  name: string;
  result: string;
  isError: boolean;
}

export interface Message {
  id: string;
  role: MessageRole;
  content: string;
  timestamp: number;
  attachments?: ChatAttachment[];
  reasoning?: string;
  toolCalls?: ToolCallInfo[];
  toolResults?: ToolResultInfo[];
  audioUrl?: string;
  isStreaming?: boolean;
}

// ===========================================================================
// 5. 记忆
// ===========================================================================

export type MemoryType =
  | 'episodic'
  | 'semantic'
  | 'procedural'
  | 'emotional'
  | 'preference'
  | 'fact'
  | 'skill'
  | 'event'
  | 'relationship'
  | 'context'
  | 'reflection'
  | 'plan'
  | 'goal'
  | 'dream'
  | 'insight'
  | 'association'
  | 'pattern';

export interface Memory {
  id: string;
  type: MemoryType;
  content: string;
  agentId: string;
  temperature?: number;       // 记忆温度（0=冰冷永久，1=火热易失）
  importance?: number;        // 重要性 0-1
  createdAt: string;
  updatedAt: string;
  tags?: string[];
  metadata?: Metadata;
}

// ===========================================================================
// 6. WebSocket 协议（扩展聊天协议）
// ===========================================================================

/** WS 消息类型枚举 */
export type WSMessageType =
  | 'chat:send'           // 客户端 → 服务端：发送消息
  | 'chat:chunk'          // 服务端 → 客户端：流式 chunk
  | 'chat:done'           // 服务端 → 客户端：流式完成
  | 'chat:cancel'         // 客户端 → 服务端：取消生成
  | 'chat:error'          // 服务端 → 客户端：聊天错误
  | 'agent:switch'        // 客户端 → 服务端：切换 Agent
  | 'agent:switched'      // 服务端 → 客户端：切换确认
  | 'session:list'        // 双向：会话列表
  | 'session:create'      // 客户端 → 服务端：创建会话
  | 'session:created'     // 服务端 → 客户端：创建确认
  | 'error'               // 服务端 → 客户端：通用错误
  | 'ping'                // 心跳
  | 'pong';               // 心跳响应

/** WS 通用消息信封 */
export interface WSMessage {
  type: WSMessageType;
  [key: string]: Object;
}

/** chat:send 消息 */
export interface WSChatSend {
  type: 'chat:send';
  content: string;
  session_id: string;
  agent_id?: string;
  attachments?: ChatAttachment[];
}

/** chat:chunk 消息 */
export interface WSChatChunk {
  type: 'chat:chunk';
  session_id: string;
  content: string;
  index: number;
}

/** chat:done 消息 */
export interface WSChatDone {
  type: 'chat:done';
  session_id: string;
  message_id: string;
}

/** chat:cancel 消息 */
export interface WSChatCancel {
  type: 'chat:cancel';
  session_id: string;
}

/** chat:error 消息 */
export interface WSChatError {
  type: 'chat:error';
  session_id: string;
  error: string;
}

/** agent:switch 消息 */
export interface WSAgentSwitch {
  type: 'agent:switch';
  agent_id: string;
}

/** agent:switched 消息 */
export interface WSAgentSwitched {
  type: 'agent:switched';
  agent_id: string;
  config: {
    agent_id: string;
    name: string;
  };
}

/** session:list 消息（响应） */
export interface WSSessionList {
  type: 'session:list';
  sessions: Session[];
}

/** session:create 消息 */
export interface WSSessionCreate {
  type: 'session:create';
  agent_id: string;
  title?: string;
}

/** session:created 消息 */
export interface WSSessionCreated {
  type: 'session:created';
  session: Session;
}

/** 通用错误消息 */
export interface WSError {
  type: 'error';
  code: string;
  message: string;
}

// ===========================================================================
// 7. 移动端配对
// ===========================================================================

/** 配对码信息 */
export interface PairingInfo {
  code: string;            // 6 位配对码
  qrCodeUrl: string;       // 二维码图片 URL
  wsUrl: string;           // WebSocket 连接 URL
  expiresAt: number;       // 过期时间戳（毫秒）
}

/** 配对确认请求 */
export interface PairingConfirm {
  code: string;
  deviceName: string;
  deviceType: string;
}

/** 配对确认响应 */
export interface PairingConfirmed {
  wsToken: string;         // WS 连接 token
  wsUrl: string;           // WS 连接 URL
  expiresIn: number;       // token 有效期（秒）
}

// ===========================================================================
// 8. 导航
// ===========================================================================

/** 导航参数 */
export interface NavigationParam {
  [key: string]: Object;
}

// ===========================================================================
// 9. LLM 模型与 Provider
// ===========================================================================

export type ModelType = 'text' | 'image' | 'audio';
export type ProviderCategory = 'paid' | 'free' | 'local';
export type ProviderStatus = 'available' | 'unavailable' | 'not_configured' | 'not_ready';
export type ProviderHealth = 'healthy' | 'unhealthy' | 'unknown';

export interface ModelItem {
  id: string;
  name: string;
  provider_id: string;
  type: ModelType;
  tags: string[];
  enabled: boolean;
  capabilities: string[];
  is_active: boolean;
  context_window?: number;
  max_tokens?: number;
  pricing?: { input: number; output: number };
  owned_by?: string;
}

export interface Provider {
  id: string;
  name: string;
  icon: string;
  iconSrc?: string;
  color: string;
  type: 'builtin' | 'custom';
  category: ProviderCategory;
  status: ProviderStatus;
  statusLabel: string;
  base_url: string;
  api_key?: string;
  api_key_configured: boolean;
  auth_method?: 'api_key' | 'bearer';
  protocol: 'openai' | 'anthropic';
  models: ModelItem[];
  model_count: number;
  enabled: boolean;
  health: ProviderHealth;
  priority: number;
  description?: string;
  config?: Record<string, Object>;
  headers?: Record<string, string>;
  gen_params?: Record<string, Object>;
}

export interface DefaultLLMConfig {
  provider_id: string;
  model_id: string;
}

export interface GenerationParams {
  temperature: number;
  max_tokens: number;
  stream_mode: boolean;
}

// ===========================================================================
// 10. 注册与用户管理（RegisterPage）
// ===========================================================================

/** 注册表单 */
export interface RegisterForm {
  username: string;
  email: string;
  password: string;
  confirmPassword: string;
  agreedTerms: boolean;
}

/** 注册响应 */
export interface RegisterResult {
  userId: string;
  username: string;
  email: string;
  createdAt: string;
}

// ===========================================================================
// 11. 知识库（KnowledgePage）
// ===========================================================================

export type KnowledgeStatus = 'ready' | 'indexing' | 'error' | 'pending';

export interface KnowledgeItem {
  id: string;
  title: string;
  content: string;
  summary?: string;
  source: string;            // 来源：upload / url / manual
  sourceUrl?: string;
  category?: string;         // 分类标签
  tags?: string[];
  status: KnowledgeStatus;
  fileSize?: number;         // 字节数
  wordCount?: number;
  agentId?: string;          // 关联 Agent
  createdAt: string;
  updatedAt: string;
  indexedAt?: string;
  errorMessage?: string;
}

export interface KnowledgeQuery {
  keyword?: string;
  category?: string;
  tags?: string[];
  agentId?: string;
  status?: KnowledgeStatus;
  page?: number;
  size?: number;
}

// ===========================================================================
// 12. Agent 渠道（AgentChannelPage）
// ===========================================================================

export type ChannelType =
  | 'feishu'
  | 'dingtalk'
  | 'telegram'
  | 'discord'
  | 'wechat'
  | 'webhook'
  | 'api'
  | 'email';

export type ChannelStatus = 'connected' | 'disconnected' | 'error' | 'disabled';

export interface ChannelInfo {
  id: string;
  agentId: string;
  type: ChannelType;
  name: string;              // 渠道实例名称
  status: ChannelStatus;
  config: Record<string, Object>;
  webhookUrl?: string;       // 入站回调地址
  appId?: string;            // 第三方应用 ID
  connectedAt?: string;
  lastEventAt?: string;
  errorMessage?: string;
  enabled: boolean;
  createdAt: string;
  updatedAt: string;
}

// ===========================================================================
// 13. 应用设置（SettingPage）
// ===========================================================================

export type SettingType = 'toggle' | 'select' | 'input' | 'slider' | 'action';

export interface SettingItem {
  key: string;               // 设置项唯一标识（持久化键名）
  label: string;
  description?: string;
  type: SettingType;
  value: Object;             // 当前值
  defaultValue: Object;
  options?: { label: string; value: Object }[];  // select 类型选项
  min?: number;              // slider 最小值
  max?: number;              // slider 最大值
  step?: number;             // slider 步长
  group: string;             // 分组：general / appearance / notification / privacy / about
  requiresRestart?: boolean;
}

export interface SettingGroup {
  key: string;
  title: string;
  icon?: string;
  items: SettingItem[];
}

// ===========================================================================
// 14. 系统健康详情（HealthPage）
// ===========================================================================

export interface ServiceHealth {
  name: string;              // 服务名：api / db / redis / llm / ws
  status: 'healthy' | 'degraded' | 'down' | 'unknown';
  latency?: number;          // 毫秒
  uptime?: number;           // 秒
  version?: string;
  lastCheckAt?: string;
  message?: string;
  metrics?: Record<string, number>;
}

export interface SystemHealth {
  status: 'healthy' | 'degraded' | 'down';
  score: number;             // 0-100
  services: ServiceHealth[];
  checkedAt: string;
}

// ===========================================================================
// 15. 认知层（P2）
// ===========================================================================

/** 经验知识条目 */
export interface Experience {
  id: string;
  agentId: string;
  title: string;
  content: string;
  category: string;          // 工作场景/技术细节/用户偏好/失败教训
  importance: number;        // 0-1
  createdAt: string;
  updatedAt: string;
  lastActivatedAt?: string;
  activationCount: number;
}

/** 知识图谱节点 */
export interface KnowledgeNode {
  id: string;
  agentId: string;
  label: string;
  type: 'concept' | 'entity' | 'event' | 'fact';
  properties?: Metadata;
  weight?: number;
}

/** 知识图谱边 */
export interface KnowledgeEdge {
  id: string;
  source: string;
  target: string;
  relation: string;
  weight?: number;
}

/** 知识图谱（节点+边集合） */
export interface KnowledgeGraph {
  nodes: KnowledgeNode[];
  edges: KnowledgeEdge[];
}

/** 元认知记录 */
export interface MetacognitionRecord {
  id: string;
  agentId: string;
  thoughtId: string;
  type: 'monitoring' | 'control' | 'evaluation';
  content: string;
  confidence: number;        // 0-1
  createdAt: string;
}

/** 反思记录 */
export interface ReflectionRecord {
  id: string;
  agentId: string;
  trigger: string;
  content: string;
  insights: string[];
  improvements: string[];
  createdAt: string;
}

/** 成长记录 */
export interface GrowthRecord {
  id: string;
  agentId: string;
  dimension: 'knowledge' | 'skill' | 'emotion' | 'social' | 'meta';
  level: number;
  experience: number;
  milestones: string[];
  updatedAt: string;
}

// ===========================================================================
// 16. 能力（P2）
// ===========================================================================

/** 规则类型 */
export type RuleType = 'permission' | 'restriction' | 'behavior' | 'workflow';

/** 规则状态 */
export type RuleStatus = 'active' | 'inactive' | 'archived';

/** 智能体规则 */
export interface Rule {
  id: string;
  agentId: string;
  name: string;
  type: RuleType;
  status: RuleStatus;
  priority: number;          // 越小优先级越高
  condition: string;
  action: string;
  description?: string;
  createdAt: string;
  updatedAt: string;
}

/** 智能体文件 */
export interface AgentFile {
  id: string;
  agentId: string;
  name: string;
  path: string;
  size: number;
  mimeType: string;
  uploadedAt: string;
  uploadedBy?: string;
}

/** 媒体资产类型 */
export type MediaAssetType = 'image' | 'audio' | 'video' | 'document';

/** 媒体资产 */
export interface MediaAsset {
  id: string;
  agentId: string;
  type: MediaAssetType;
  name: string;
  url: string;
  thumbnailUrl?: string;
  size: number;
  duration?: number;        // 秒，音视频适用
  createdAt: string;
}

// ===========================================================================
// 17. 运行时（P2）
// ===========================================================================

/** 调度任务状态 */
export type ScheduleTaskStatus = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';

/** 调度任务 */
export interface ScheduleTask {
  id: string;
  agentId: string;
  name: string;
  cron: string;             // cron 表达式
  status: ScheduleTaskStatus;
  lastRunAt?: string;
  nextRunAt?: string;
  payload?: Metadata;
  createdAt: string;
}

/** 上下文消息角色 */
export type ContextRole = 'system' | 'user' | 'assistant' | 'tool';

/** 上下文消息 */
export interface ContextMessage {
  id: string;
  sessionId: string;
  role: ContextRole;
  content: string;
  tokens: number;
  createdAt: string;
  metadata?: Metadata;
}

/** 计算机任务（Computer Use） */
export interface ComputerTask {
  id: string;
  agentId: string;
  action: string;            // click/type/scroll/screenshot
  status: ScheduleTaskStatus;
  target?: string;
  result?: string;
  startedAt: string;
  finishedAt?: string;
}

/** 追踪条目级别 */
export type TraceLevel = 'debug' | 'info' | 'warn' | 'error';

/** 追踪条目 */
export interface TraceEntry {
  id: string;
  agentId: string;
  sessionId: string;
  level: TraceLevel;
  event: string;
  payload?: Metadata;
  timestamp: string;
  durationMs?: number;
}

/** 轨迹点 */
export interface TrajectoryPoint {
  id: string;
  agentId: string;
  sessionId: string;
  step: number;
  action: string;
  observation: string;
  reward?: number;
  timestamp: string;
}

/** 休眠状态 */
export interface SleepStatus {
  agentId: string;
  isSleeping: boolean;
  sleepSince?: string;
  wakeAt?: string;
  mode: 'idle' | 'light' | 'deep';
  pendingTasks: number;
}

/** 防火墙规则动作 */
export type FirewallAction = 'allow' | 'deny' | 'ask';

/** 防火墙规则 */
export interface FirewallRule {
  id: string;
  agentId: string;
  resource: string;          // URL/IP/路径
  action: FirewallAction;
  scope: 'inbound' | 'outbound' | 'both';
  enabled: boolean;
  createdAt: string;
}

// ===========================================================================
// 18. 个性（P2）
// ===========================================================================

/** 情绪记录 */
export interface Emotion {
  id: string;
  agentId: string;
  type: string;              // happy/sad/angry/surprised/neutral
  intensity: number;         // 0-1
  trigger?: string;
  createdAt: string;
}

/** 个性维度 */
export interface Personality {
  agentId: string;
  openness: number;          // 0-1
  conscientiousness: number;
  extraversion: number;
  agreeableness: number;
  neuroticism: number;
  description?: string;
  updatedAt: string;
}

// ===========================================================================
// 19. 知识技能扩展（P2）
// ===========================================================================

/** 技能状态 */
export type SkillStatus = 'draft' | 'published' | 'deprecated';

/** 技能 */
export interface Skill {
  id: string;
  name: string;
  description: string;
  category: string;
  version: string;
  status: SkillStatus;
  author: string;
  installs: number;
  rating: number;            // 0-5
  tags: string[];
  manifest?: Metadata;
  publishedAt?: string;
}

/** AIGC 任务状态 */
export type AIGCTaskStatus = 'queued' | 'processing' | 'succeeded' | 'failed';

/** AIGC 任务 */
export interface AIGCTask {
  id: string;
  agentId: string;
  type: 'text' | 'image' | 'audio' | 'video';
  prompt: string;
  status: AIGCTaskStatus;
  resultUrl?: string;
  errorMessage?: string;
  createdAt: string;
  finishedAt?: string;
}

/** 工具层定义 */
export interface ToolLayer {
  id: string;
  name: string;
  description: string;
  enabled: boolean;
  tools: string[];          // 工具 id 列表
  priority: number;
}

// ===========================================================================
// 20. 协作与工作流（P2）
// ===========================================================================

/** 项目状态 */
export type ProjectStatus = 'planning' | 'active' | 'paused' | 'completed' | 'archived';

/** 项目 */
export interface Project {
  id: string;
  name: string;
  description: string;
  status: ProjectStatus;
  owner: string;
  members: string[];
  startDate?: string;
  endDate?: string;
  createdAt: string;
  updatedAt: string;
}

/** 团队角色 */
export type TeamRole = 'owner' | 'admin' | 'member' | 'viewer';

/** 团队 */
export interface Team {
  id: string;
  name: string;
  description?: string;
  members: Array<{ userId: string; role: TeamRole }>;
  createdAt: string;
}

/** 任务状态 */
export type TaskStatus = 'todo' | 'in_progress' | 'review' | 'done' | 'blocked';

/** 任务优先级 */
export type TaskPriority = 'low' | 'medium' | 'high' | 'urgent';

/** 任务 */
export interface Task {
  id: string;
  projectId: string;
  title: string;
  description?: string;
  status: TaskStatus;
  priority: TaskPriority;
  assignee?: string;
  dueDate?: string;
  tags: string[];
  createdAt: string;
  updatedAt: string;
}

/** 工作流状态 */
export type WorkflowStatus = 'draft' | 'active' | 'paused' | 'archived';

/** 工作流节点 */
export interface WorkflowNode {
  id: string;
  type: 'start' | 'task' | 'decision' | 'end';
  name: string;
  config?: Metadata;
}

/** 工作流 */
export interface Workflow {
  id: string;
  name: string;
  description?: string;
  status: WorkflowStatus;
  nodes: WorkflowNode[];
  edges: Array<{ source: string; target: string; condition?: string }>;
  version: string;
  createdAt: string;
  updatedAt: string;
}

// ===========================================================================
// 21. 渠道扩展（P2）
// ===========================================================================

/** 渠道集成状态 */
export type IntegrationStatus = 'connected' | 'disconnected' | 'error' | 'syncing';

/** 渠道集成（扩展 ChannelInfo） */
export interface ChannelIntegration {
  id: string;
  channelId: string;
  type: ChannelType;
  name: string;
  status: IntegrationStatus;
  capabilities: string[];    // messaging/file/audit/...
  lastSyncAt?: string;
  config?: Metadata;
}

/** 会话同步记录 */
export interface SessionSync {
  id: string;
  sessionId: string;
  sourceChannel: string;
  targetChannel: string;
  lastSyncedAt: string;
  messageCount: number;
  status: 'synced' | 'partial' | 'failed';
}

// ===========================================================================
// 22. 监控与管理（P2）
// ===========================================================================

/** 统计指标 */
export interface Stat {
  key: string;
  label: string;
  value: number;
  unit?: string;
  trend?: number;            // 与上一周期对比，百分比
  period: 'day' | 'week' | 'month' | 'year';
  recordedAt: string;
}

/** 监控指标 */
export interface MonitorMetric {
  name: string;
  value: number;
  unit: string;
  timestamp: string;
  tags?: Metadata;
}

/** 日志级别 */
export type LogLevel = 'debug' | 'info' | 'warn' | 'error' | 'fatal';

/** 日志条目 */
export interface LogEntry {
  id: string;
  level: LogLevel;
  source: string;            // 模块名
  message: string;
  context?: Metadata;
  timestamp: string;
  traceId?: string;
}

/** 通知类型 */
export type NotificationType = 'info' | 'success' | 'warning' | 'error';

/** 通知 */
export interface NotificationItem {
  id: string;
  type: NotificationType;
  title: string;
  body: string;
  read: boolean;
  actionUrl?: string;
  createdAt: string;
}

/** 文件项类型 */
export type FileItemType = 'file' | 'folder';

/** 文件项 */
export interface FileItem {
  id: string;
  name: string;
  type: FileItemType;
  path: string;
  size: number;
  mimeType?: string;
  parentId?: string;
  modifiedAt: string;
  permissions?: string;
}

// ===========================================================================
// 23. NEURON 网络（P2）
// ===========================================================================

/** 神经元状态 */
export type NeuronState = 'idle' | 'active' | 'firing' | 'inhibited';

/** 神经元 */
export interface Neuron {
  id: string;
  agentId: string;
  name: string;
  state: NeuronState;
  connections: number;
  activation: number;        // 0-1
  threshold: number;         // 0-1
  lastFiredAt?: string;
  metadata?: Metadata;
}

// ===========================================================================
// 24. 协作扩展与市场（P3）
// ===========================================================================

/** 协作模板 */
export interface CollaborationTemplate {
  id: string;
  name: string;
  description?: string;
  category: string;            // project/team/workflow
  steps: Array<{ name: string; description?: string; order: number }>;
  isPublic: boolean;
  usageCount: number;
  createdAt: string;
  updatedAt: string;
}

/** 协作历史记录 */
export interface CollaborationHistory {
  id: string;
  collaborationId: string;
  action: string;              // create/update/complete/archive
  actor: string;               // userId or agentId
  before?: Metadata;
  after?: Metadata;
  timestamp: string;
  note?: string;
}

/** 协作发起请求 */
export interface CollaborationInitiate {
  id: string;
  templateId?: string;
  type: 'project' | 'team' | 'task' | 'workflow';
  name: string;
  description?: string;
  participants: string[];       // userId 或 agentId 列表
  status: 'pending' | 'initiated' | 'failed';
  initiatedAt?: string;
  createdAt: string;
}

/** Webhook 配置 */
export type WebhookEvent = 'message.received' | 'agent.created' | 'task.completed' | 'memory.created';
export type WebhookStatus = 'active' | 'paused' | 'error';

export interface Webhook {
  id: string;
  name: string;
  url: string;
  events: WebhookEvent[];
  status: WebhookStatus;
  secret?: string;             // 签名密钥
  lastTriggeredAt?: string;
  successCount: number;
  failureCount: number;
  createdAt: string;
  updatedAt: string;
}

/** 市场商品 */
export type MarketplaceCategory = 'agent' | 'skill' | 'template' | 'plugin' | 'workflow';
export type MarketplaceItemType = 'free' | 'paid' | 'subscription';

export interface MarketplaceItem {
  id: string;
  name: string;
  description: string;
  category: MarketplaceCategory;
  itemType: MarketplaceItemType;
  price: number;
  currency: string;
  author: string;
  rating: number;
  downloadCount: number;
  tags: string[];
  thumbnail?: string;
  publishedAt: string;
}

// ===========================================================================
// 25. 系统监控扩展（P3）
// ===========================================================================

/** 审计日志 */
export type AuditAction = 'create' | 'update' | 'delete' | 'login' | 'logout' | 'export' | 'import' | 'config_change';

export interface AuditEntry {
  id: string;
  userId: string;
  username: string;
  action: AuditAction;
  resource: string;             // 资源类型
  resourceId?: string;
  ip: string;
  userAgent?: string;
  before?: Metadata;
  after?: Metadata;
  timestamp: string;
  success: boolean;
  errorMessage?: string;
}

/** 基准测试项 */
export type BenchmarkType = 'cpu' | 'memory' | 'disk' | 'network' | 'llm_inference' | 'embedding';

export interface Benchmark {
  id: string;
  type: BenchmarkType;
  name: string;
  durationMs: number;
  iterations: number;
  avgLatencyMs: number;
  p95LatencyMs: number;
  p99LatencyMs: number;
  throughputOps?: number;
  score?: number;
  status: 'pending' | 'running' | 'completed' | 'failed';
  startedAt?: string;
  completedAt?: string;
}

/** 沙盒环境 */
export type SandboxStatus = 'created' | 'running' | 'stopped' | 'error' | 'expired';

export interface Sandbox {
  id: string;
  name: string;
  image: string;               // 容器镜像
  status: SandboxStatus;
  cpuLimit: number;             // 核数
  memoryLimitMb: number;
  diskLimitMb: number;
  exposedPorts: number[];
  envVars: Record<string, string>;
  createdAt: string;
  expiresAt: string;
  lastStartedAt?: string;
  errorMessage?: string;
}

/** 防火墙规则（系统级，区别于 AgentFirewallPage 的 agent 级） */
export type SystemFirewallAction = 'allow' | 'deny' | 'log' | 'rate_limit';

export interface SystemFirewallRule {
  id: string;
  name: string;
  sourceIp?: string;           // CIDR
  destinationPort?: number;
  protocol?: 'tcp' | 'udp' | 'icmp' | 'any';
  action: SystemFirewallAction;
  priority: number;            // 1-100
  enabled: boolean;
  hitCount: number;
  lastHitAt?: string;
  createdAt: string;
  updatedAt: string;
}

/** 分析指标 */
export type AnalyticsGranularity = 'minute' | 'hour' | 'day' | 'week' | 'month';

export interface AnalyticsPoint {
  timestamp: string;
  value: number;
  label?: string;
}

export interface AnalyticsSeries {
  id: string;
  name: string;
  metric: string;               // messages_count / token_usage / active_users
  granularity: AnalyticsGranularity;
  points: AnalyticsPoint[];
  unit: string;
  description?: string;
}

// ===========================================================================
// 26. 用户与记忆扩展（P3）
// ===========================================================================

/** 用户组 */
export interface UserGroup {
  id: string;
  name: string;
  description?: string;
  memberCount: number;
  permissions: string[];       // 权限标识列表
  leader?: string;             // 用户 ID
  createdAt: string;
  updatedAt: string;
}

/** 增强用户信息 */
export type EnhancedUserStatus = 'online' | 'idle' | 'dnd' | 'offline';
export type EnhancedUserRole = 'admin' | 'developer' | 'operator' | 'viewer' | 'guest';

export interface EnhancedUser {
  id: string;
  username: string;
  email: string;
  displayName: string;
  avatar?: string;
  status: EnhancedUserStatus;
  role: EnhancedUserRole;
  department?: string;
  title?: string;
  lastActiveAt?: string;
  loginCount: number;
  twoFactorEnabled: boolean;
  createdAt: string;
}

/** 智能体技能（区别于 SkillPool 的"技能池"概念，AgentSkill 是绑定到具体 Agent 的技能实例） */
export type AgentSkillStatus = 'equipped' | 'active' | 'cooldown' | 'disabled';

export interface AgentSkill {
  id: string;
  agentId: string;
  name: string;
  description?: string;
  level: number;               // 1-10
  experience: number;          // 0-100
  status: AgentSkillStatus;
  cooldownEndsAt?: string;
  lastUsedAt?: string;
  usageCount: number;
  equippedAt: string;
}

/** 记忆设置 */
export interface MemorySettings {
  agentId: string;
  enabled: boolean;
  capacity: number;            // 最大记忆条数
  retentionDays: number;       // 保留天数
  temperatureThreshold: number; // 温度阈值（0-1）
  autoArchive: boolean;
  autoForget: boolean;
  indexedFields: string[];     // 索引字段
  updatedAt: string;
}

/** 记忆搜索设置 */
export type MemorySearchStrategy = 'semantic' | 'keyword' | 'hybrid' | 'temporal';

export interface MemorySearchSettings {
  agentId: string;
  strategy: MemorySearchStrategy;
  topK: number;                // 返回结果数
  minScore: number;            // 0-1
  filters?: {
    types?: string[];
    tags?: string[];
    dateRange?: { start: string; end: string };
  };
  enabled: boolean;
  updatedAt: string;
}
