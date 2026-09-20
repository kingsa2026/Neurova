import axios from 'axios';
import type { Computer } from '@/types/computer';
import type { CostSummary, CostDetailed, CostCalculation } from '@/types/cost';

const API_BASE = '/api';

export const computerApi = {
  /**
   * 获取用户的所有 Computers
   */
  listUserComputers: async (): Promise<Computer[]> => {
    const response = await axios.get(`${API_BASE}/computers`);
    return response.data;
  },

  /**
   * 创建新 Computer
   */
  createComputer: async (params: {
    name: string;
    kind?: 'cloud' | 'local' | 'vps';
    engine?: string;
    company_id?: string;
  }): Promise<Computer> => {
    const response = await axios.post(`${API_BASE}/computers`, params);
    return response.data;
  },

  /**
   * 获取指定 Computer
   */
  getComputer: async (computerId: string): Promise<Computer> => {
    const response = await axios.get(`${API_BASE}/computers/${computerId}`);
    return response.data;
  },

  /**
   * 删除 Computer
   */
  deleteComputer: async (computerId: string, hard: boolean = false): Promise<void> => {
    await axios.delete(`${API_BASE}/computers/${computerId}`, { params: { hard } });
  },

  /**
   * BYOA Computer 配对
   */
  pairByOAComputer: async (computerId: string, params: {
    pair_token: string;
    host_name: string;
    available_engines: string[];
    daemon_version: string;
    supervised?: boolean;
  }): Promise<Computer> => {
    const response = await axios.post(
      `${API_BASE}/computers/${computerId}/pair`,
      params
    );
    return response.data;
  },

  /**
   * 撤销 Computer 访问
   */
  revokeComputer: async (computerId: string): Promise<Computer> => {
    const response = await axios.post(`${API_BASE}/computers/${computerId}/revoke`);
    return response.data;
  },

  /**
   * 发送 heartbeat
   */
  heartbeat: async (computerId: string, version?: string): Promise<{ status: string }> => {
    const response = await axios.post(
      `${API_BASE}/computers/${computerId}/heartbeat`,
      {},
      { params: { version } }
    );
    return response.data;
  },

  /**
   * 列出 Computer 上的 Agents
   */
  listAgentsOnComputer: async (computerId: string): Promise<string[]> => {
    const response = await axios.get(`${API_BASE}/computers/${computerId}/agents`);
    return response.data;
  },

  /**
   * 获取 Cloud Computer
   */
  getCloudComputer: async (companyId?: string): Promise<Computer> => {
    const response = await axios.get(`${API_BASE}/computers/cloud`, { params: { company_id: companyId } });
    return response.data;
  },

  /**
   * 清理离线 Computers
   */
  cleanupOfflineComputers: async (timeoutMinutes: number = 90): Promise<{ cleaned_count: number }> => {
    const response = await axios.post(`${API_BASE}/computers/cleanup-offline`, {}, {
      params: { timeout_minutes: timeoutMinutes }
    });
    return response.data;
  },
};

export const costApi = {
  /**
   * 获取 Agent 成本汇总
   */
  getAgentCostSummary: async (agentId: string, hours: number = 24): Promise<CostSummary> => {
    const response = await axios.get(`${API_BASE}/cost/agent/${agentId}/summary`, {
      params: { hours }
    });
    return response.data;
  },

  /**
   * 获取 Agent 详细成本记录
   */
  getAgentCostDetailed: async (agentId: string, params: {
    hours?: number;
    provider?: string;
    model?: string;
  }): Promise<CostDetailed> => {
    const response = await axios.get(`${API_BASE}/cost/agent/${agentId}/detailed`, { params });
    return response.data;
  },

  /**
   * 获取公司成本汇总
   */
  getCompanyCostSummary: async (companyId: string, hours: number = 24): Promise<any> => {
    const response = await axios.get(`${API_BASE}/cost/company/${companyId}/summary`, {
      params: { hours }
    });
    return response.data;
  },

  /**
   * 获取公司成本排行榜
   */
  getCompanyCostLeaderboard: async (companyId: string, params: {
    hours?: number;
    limit?: number;
  }): Promise<any> => {
    const response = await axios.get(`${API_BASE}/cost/company/${companyId}/leaderboard`, { params });
    return response.data;
  },

  /**
   * 计算 LLM 调用成本
   */
  calculateLLMCost: async (params: {
    provider: string;
    model: string;
    input_tokens: number;
    output_tokens?: number;
    cache_read_tokens?: number;
    cache_write_tokens?: number;
  }): Promise<CostCalculation> => {
    const response = await axios.post(`${API_BASE}/cost/calculate`, params);
    return response.data;
  },

  /**
   * 获取每小时成本汇总
   */
  getHourlyRollup: async (params: {
    hours: number;
    company_id?: string;
  }): Promise<any> => {
    const response = await axios.get(`${API_BASE}/cost/rollup/hourly`, { params });
    return response.data;
  },

  /**
   * 获取实时成本仪表盘
   */
  getRealtimeDashboard: async (companyId: string, windowMinutes: number = 60): Promise<any> => {
    const response = await axios.get(`${API_BASE}/cost/dashboard/realtime`, {
      params: { company_id: companyId, window_minutes: windowMinutes }
    });
    return response.data;
  },
};
