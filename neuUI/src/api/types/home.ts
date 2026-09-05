/**
 * 首页统计数据类型定义
 */

/** 记忆分类统计 */
export interface MemoryCategories {
  short_term: number;
  long_term: number;
  episodic: number;
  semantic: number;
}

/** 技能分类统计 */
export interface SkillCategories {
  conversation: number;
  code: number;
  search: number;
  creation: number;
  other: number;
}

/** Agent能力评估 */
export interface AgentCapabilities {
  reasoning: number;
  creativity: number;
  knowledge: number;
  communication: number;
  problem_solving: number;
}

/** 趋势数据 */
export interface TrendValues {
  agent_trend: number;
  conversation_trend: number;
  memory_trend: number;
  token_trend: number;
  plugin_trend: number;
}

/** 统计数据 */
export interface HomeStats {
  agent_count: number;
  conversation_count: number;
  memory_count: number;
  token_consumption: number;
  plugin_count: number;
  public_skill_count: number;
  sleep_count: number;
  sleep_log_count: number;
  llm_call_count: number;
  evolution_count: number;
  custom_skill_count: number;
  skill_iteration_count: number;
}

/** 系统状态 */
export interface SystemStatus {
  status: string;
  uptime: string;
  version: string;
}

/** 推荐操作 */
export interface RecommendedAction {
  title: string;
  description: string;
  action: string;
  priority: 'high' | 'medium' | 'normal';
}

/** 快速统计 */
export interface QuickStats {
  total_conversations: number;
  total_memories: number;
  total_skills: number;
}

/** 首页数据响应 */
export interface HomeDataResponse {
  welcome_message: string;
  quick_stats: QuickStats;
  stats: HomeStats;
  memory_categories?: MemoryCategories;
  skill_categories?: SkillCategories;
  agent_capabilities?: AgentCapabilities;
  trends?: TrendValues;
  recommended_actions: RecommendedAction[];
  system_status: SystemStatus;
}

/** 趋势数据 */
export interface TrendData {
  labels: string[];
  data: number[];
}

/** 趋势数据响应 */
export interface TrendsResponse {
  agent_trend: TrendData;
  token_trend: TrendData;
  memory_trend: TrendData;
  conversation_trend: TrendData;
  skill_trend: TrendData;
  llm_trend: TrendData;
}

/** API 统一响应格式 */
export interface APIResponse<T> {
  code: number;
  message: string;
  data: T;
  request_id?: string;
}
