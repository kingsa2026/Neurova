import { request } from '@/api';

export interface SystemStats {
  status: string;
  uptime: string;
  version: string;
  agents_count: number;
  default_agent_id?: string;
  memory_enabled: boolean;
  channels_enabled: boolean;
  multi_user_enabled: boolean;
}

export interface UserStats {
  total_users: number;
  total_groups: number;
  active_users: number;
}

export interface MemoryStats {
  total_memories: number;
  by_category: Record<string, number>;
  by_emotion: Record<string, number>;
  temperature_distribution: Record<string, number>;
}

export interface AgentStats {
  agent_id: string;
  is_default?: boolean;
  memory_enabled: boolean;
  memory_stats?: Record<string, unknown>;
}

export interface AgentStatsResponse {
  total_agents: number;
  agents: AgentStats[];
}

export interface ControlDashboard {
  system_status: string;
  key_metrics: {
    total_requests: number;
    success_rate: number;
    average_response_time: number;
  };
  recent_activities: Record<string, unknown>[];
}

export const statsAPI = {
  getSystemStats: () => request.get('/stats/system'),

  getUserStats: () => request.get('/stats/users'),

  getMemoryStats: (agentId?: string) =>
    request.get('/stats/memories', agentId ? { params: { agent_id: agentId } } : {}),

  getAgentsStats: () => request.get('/stats/agents'),

  getControlDashboard: () => request.get('/control/dashboard'),
};
