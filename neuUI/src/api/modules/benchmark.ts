import { request } from '@/api'

export interface BenchmarkRunRequest {
  user_id: string
  agent_id: string
  suite: string
  params?: Record<string, unknown>
}

export interface ListRunsRequest {
  user_id?: string
}

export const benchmarkAPI = {
  listSuites: () => request.get('/benchmark/suites'),
  run: (data: BenchmarkRunRequest) =>
    request.post('/benchmark/run', data),
  listRuns: (params?: ListRunsRequest) =>
    request.get('/benchmark/runs', { params }),
  getRun: (runId: string, userId: string) =>
    request.get('/benchmark/runs/' + runId, { params: { user_id: userId } }),
  getAgentBenchmarks: (agentId: string, userId: string) =>
    request.get('/benchmark/agents/' + agentId, { params: { user_id: userId } }),
  compareAgents: (userId: string, agentIds: string[]) =>
    request.get('/benchmark/compare', { params: { user_id: userId, agent_ids: agentIds.join(',') } }),
}
