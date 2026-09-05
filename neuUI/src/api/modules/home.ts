import { request } from '@/api';

export interface AgentCapabilities {
  reasoning: number;
  creativity: number;
  knowledge: number;
  communication: number;
  problem_solving: number;
}

export interface MemoryCategories {
  short_term: number;
  long_term: number;
  episodic: number;
  semantic: number;
}

export interface SkillCategories {
  conversation: number;
  code: number;
  search: number;
  creation: number;
  other: number;
}

export interface QuickStats {
  total_conversations: number;
  total_memories: number;
  total_skills: number;
}

export interface Stats {
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

export interface Trends {
  agent_trend: number;
  conversation_trend: number;
  memory_trend: number;
  token_trend: number;
  plugin_trend: number;
}

export interface SystemStatus {
  status: string;
  uptime: string;
  version: string;
}

export interface RecommendedAction {
  title: string;
  description: string;
  action: string;
  priority: string;
}

export interface HomeDataResponse {
  welcome_message: string;
  quick_stats: QuickStats;
  stats: Stats;
  memory_categories: MemoryCategories;
  skill_categories: SkillCategories;
  agent_capabilities: AgentCapabilities;
  trends: Trends;
  recommended_actions: RecommendedAction[];
  system_status: SystemStatus;
}

export interface TrendItem {
  labels: string[];
  data: number[];
}

export interface TrendsResponse {
  agent_trend: TrendItem;
  token_trend: TrendItem;
  memory_trend: TrendItem;
  conversation_trend: TrendItem;
  skill_trend: TrendItem;
  llm_trend: TrendItem;
}

export const homeAPI = {
  getHomeData: () => request.get('/home/data'),

  getTrends: (days: number = 7) =>
    request.get('/home/trends', { params: { days } }),
};
