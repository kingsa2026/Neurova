/**
 * 通用 API 类型定义
 * 用于替换代码中所有的 any 类型
 */

// ==================== 通用响应类型 ====================

/** 后端统一响应格式 */
export interface ApiResponse<T = unknown> {
  success: boolean
  code: number
  message: string
  data: T
}

/** 分页响应 */
export interface PaginatedResponse<T> {
  items: T[]
  total: number
  page: number
  page_size: number
  has_more: boolean
}

/** 通用键值对 */
export type StringRecord = Record<string, string>
export type UnknownRecord = Record<string, unknown>

// ==================== 工作流相关类型 ====================

export interface WorkflowStep {
  step_id: string
  name: string
  description?: string
  action_type?: string
  agent_id?: string
  skills?: string[]
  prompt_template?: string
  position_x?: number
  position_y?: number
  action_config?: UnknownRecord
  on_success?: string
  on_failure?: string
  timeout?: number
  status?: string
}

export interface Workflow {
  id: string
  workflow_id: string
  name: string
  description?: string
  trigger_type?: string
  trigger_config?: UnknownRecord
  steps?: WorkflowStep[]
  is_active?: boolean
  project_id?: string
  created_at?: string
  updated_at?: string
}

export interface WorkflowExecution {
  id: string
  workflow_id: string
  status: string
  context?: UnknownRecord
  result?: UnknownRecord
  started_at?: string
  completed_at?: string
  error?: string
}

export interface WorkflowEdge {
  source_step_id: string
  target_step_id: string
  edge_type?: string
  label?: string
}

export interface WorkflowViewport {
  zoom: number
  offset_x: number
  offset_y: number
}

// ==================== 调度器相关类型 ====================

export interface ScheduleConfig {
  cron?: string
  timezone?: string
  interval_seconds?: number
  run_at?: string
}

export interface TaskRequest {
  url?: string
  method?: string
  headers?: UnknownRecord
  body?: unknown
  command?: string
}

export interface RetryPolicy {
  max_retries?: number
  retry_delay_seconds?: number
  backoff_multiplier?: number
}

export interface NotificationConfig {
  on_success?: boolean
  on_failure?: boolean
  channels?: string[]
  recipients?: string[]
}

export interface TaskDependency {
  task_id: string
  type: string
}

export interface SchedulerTask {
  id: string
  name: string
  description?: string
  type?: string
  enabled: boolean
  priority?: string
  schedule?: ScheduleConfig
  request?: TaskRequest
  dependencies?: TaskDependency[]
  retry_policy?: RetryPolicy
  notifications?: NotificationConfig
  max_execution_time?: number
  tags?: string[]
  created_by?: string
  created_at?: string
  updated_at?: string
  next_run_at?: string
  last_run_at?: string
  status?: string
}

export interface TaskExecution {
  id: string
  task_id: string
  status: string
  started_at?: string
  completed_at?: string
  result?: unknown
  error?: string
  duration_ms?: number
  logs?: string[]
}

export interface TaskStats {
  total_executions: number
  successful: number
  failed: number
  avg_duration_ms: number
  last_execution?: TaskExecution
}

export interface SchedulerOverview {
  total_tasks: number
  enabled_tasks: number
  running_executions: number
  recent_failures: number
}

export interface CronValidation {
  valid: boolean
  next_runs?: string[]
  error?: string
}

// ==================== 聊天相关类型 ====================

export interface ChatSession {
  id: string
  title?: string
  agent_id: string
  created_at: string
  updated_at: string
  message_count?: number
  last_message?: string
}

export interface RawChatMessage {
  role: string
  content: string
  timestamp?: string | number
  reasoning_content?: string
  reasoning?: string
  tool_calls?: ToolCallMessage[]
  tool_messages?: ToolCallMessage[]
  message?: string
}

export interface ToolCallMessage {
  id?: string
  tool_name: string
  params?: UnknownRecord
  result?: string
  success?: boolean
}

export interface StreamCallbacks {
  onReasoning?: (content: string) => void
  onToolCall?: (toolName: string, params: UnknownRecord) => void
  onToolResult?: (toolName: string, result: string, success: boolean) => void
  onMessage?: (content: string) => void
  onDone?: (reply: string, attachmentIds?: string[]) => void
  onError?: (error: string) => void
}

export interface StreamOptions {
  agent_id: string
  message: string
  stream: boolean
  session_id?: string
}

export interface SendMessageResult {
  reply: string
  type: string
  agent_id: string
  session_id?: string
  attachment_ids?: string[]
  metadata?: UnknownRecord
  timestamp: string
}

export interface MediaUploadResult {
  id: string
  url: string
  filename: string
  size: number
  mime_type: string
}

// ==================== Agent 配置相关类型 ====================

export interface AgentConfig {
  agentId: string
  name: string
  description: string
  workspacePath: string
  personality: string
  constitution: string
  llmProvider: string
  llmModel: string
  llmBaseUrl: string
  llmTemperature: number
  maxTokens: number
  enableMemory: boolean
  enableStreaming: boolean
  ttsEnabled: boolean
  ttsVoice: string
  ttsSpeed: number
  ttsPitch: number
  showThinking: boolean
  showToolMessages: boolean
  _raw?: UnknownRecord
}

export interface RawAgentData {
  agent_id?: string
  id?: string
  name?: string
  description?: string
  llm_model?: string
  llm_provider?: string
  personality?: string
  constitution?: string
  status?: string
  memory_count?: number
  skill_count?: number
  tts_enabled?: boolean
  tts_voice?: string
  tts_speed?: number
  tts_pitch?: number
}

export interface RawAgentConfig {
  agent_id?: string
  name?: string
  description?: string
  workspace_path?: string
  personality?: string
  constitution?: string
  llm_provider?: string
  llm_model?: string
  llm_base_url?: string
  llm_temperature?: number
  max_tokens?: number
  enable_memory?: boolean
  enable_streaming?: boolean
  tts_enabled?: boolean
  tts_voice?: string
  tts_speed?: number
  tts_pitch?: number
  show_thinking?: boolean
  show_tool_messages?: boolean
  [key: string]: unknown
}

// ==================== 知识库相关类型 ====================

export interface KnowledgeBase {
  id: string
  name: string
  description?: string
  agent_id?: string
  document_count?: number
  created_at?: string
  updated_at?: string
  status?: string
  embedding_model?: string
}

export interface KnowledgeDocument {
  id: string
  name: string
  content?: string
  file_path?: string
  file_type?: string
  file_size?: number
  chunk_count?: number
  status?: string
  created_at?: string
  metadata?: UnknownRecord
}

// ==================== 记忆相关类型 ====================

export interface MemoryItem {
  id: string
  content: string
  type?: string
  category?: string
  importance?: number
  temperature?: number
  access_count?: number
  created_at?: string
  updated_at?: string
  metadata?: UnknownRecord
}

export interface MemorySearchResult {
  memory: MemoryItem
  score: number
  highlights?: string[]
}

// ==================== 技能相关类型 ====================

export interface Skill {
  id: string
  name: string
  description?: string
  version?: string
  author?: string
  category?: string
  enabled?: boolean
  parameters?: UnknownRecord
  created_at?: string
}

// ==================== 模型相关类型 ====================

export interface ModelInfo {
  id: string
  name: string
  provider?: string
  description?: string
  capabilities?: string[]
  context_window?: number
  pricing?: {
    input?: number
    output?: number
    unit?: string
  }
  status?: string
}

// ==================== Webhook 相关类型 ====================

export interface Webhook {
  id: string
  name: string
  url: string
  events?: string[]
  secret?: string
  enabled?: boolean
  created_at?: string
  last_triggered_at?: string
}

// ==================== 通知相关类型 ====================

export interface Notification {
  id: string
  title: string
  message: string
  type?: string
  read?: boolean
  created_at?: string
  metadata?: UnknownRecord
}

// ==================== 审计相关类型 ====================

export interface AuditLog {
  id: string
  action: string
  user_id?: string
  username?: string
  resource_type?: string
  resource_id?: string
  details?: UnknownRecord
  ip_address?: string
  created_at?: string
}

// ==================== 设置相关类型 ====================

export interface SystemSettings {
  [key: string]: unknown
}

export interface UserSettings {
  [key: string]: unknown
}

// ==================== 统计相关类型 ====================

export interface DashboardStats {
  total_agents?: number
  total_memories?: number
  total_conversations?: number
  total_skills?: number
  [key: string]: unknown
}

export interface HealthCheck {
  status: string
  version?: string
  uptime?: number
  checks?: Record<string, HealthCheckDetail>
}

export interface HealthCheckDetail {
  status: string
  message?: string
  latency_ms?: number
}

// ==================== 防火墙相关类型 ====================

export interface FirewallRule {
  id: string
  name: string
  type: string
  action: string
  pattern?: string
  enabled?: boolean
  created_at?: string
}

// ==================== 协作相关类型 ====================

export interface CollaborationTemplate {
  id: string
  name: string
  description?: string
  agents?: string[]
  steps?: UnknownRecord[]
  created_at?: string
}

// ==================== Channel 相关类型 ====================

export interface Channel {
  id: string
  name: string
  description?: string
  type?: string
  enabled?: boolean
  config?: UnknownRecord
  created_at?: string
}

// ==================== Provider 相关类型 ====================

export interface LLMProvider {
  id: string
  name: string
  type?: string
  base_url?: string
  api_key?: string
  models?: string[]
  enabled?: boolean
  config?: UnknownRecord
}

// ==================== 睡眠/梦境相关类型 ====================

export interface SleepReport {
  id: string
  agent_id: string
  start_time?: string
  end_time?: string
  duration?: number
  activities?: UnknownRecord[]
  summary?: string
}

// ==================== 情感相关类型 ====================

export interface EmotionState {
  agent_id: string
  primary_emotion?: string
  emotions?: Record<string, number>
  valence?: number
  arousal?: number
  updated_at?: string
}

// ==================== Marketplace 相关类型 ====================

export interface MarketplaceItem {
  id: string
  name: string
  description?: string
  author?: string
  version?: string
  category?: string
  downloads?: number
  rating?: number
  tags?: string[]
  icon?: string
}

// ==================== Group Chat 相关类型 ====================

export interface GroupChat {
  id: string
  name: string
  participants?: string[]
  created_at?: string
  last_message_at?: string
}

// ==================== 任务相关类型 ====================

export interface Task {
  id: string
  title: string
  description?: string
  status?: string
  priority?: string
  assigned_to?: string
  due_date?: string
  created_at?: string
  updated_at?: string
}

// ==================== Trace 相关类型 ====================

export interface TraceSpan {
  id: string
  name: string
  start_time?: string
  end_time?: string
  duration_ms?: number
  status?: string
  attributes?: UnknownRecord
  parent_id?: string
}

export interface Trace {
  id: string
  name?: string
  agent_id?: string
  spans?: TraceSpan[]
  start_time?: string
  end_time?: string
  status?: string
}

// ==================== 下载进度事件 ====================

export interface DownloadProgressEvent {
  target?: {
    responseText?: string
  }
  loaded: number
  total?: number
}

// ==================== Axios 扩展类型 ====================

export interface AxiosProgressEvent {
  loaded: number
  total?: number
}
