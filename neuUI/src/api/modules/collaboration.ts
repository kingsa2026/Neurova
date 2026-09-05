import { request } from '@/api'

export interface CapabilityRegistration {
  agent_id: string
  agent_name: string
  capabilities: Array<{ name: string; category?: string; level?: string; description?: string; keywords?: string[]; examples?: unknown[]; metrics?: Record<string, unknown> }>
  status?: string
}

export interface CollaborationRequest {
  template_id?: string
  participants: string[]
  task_description: string
  required_capabilities?: string[]
  priority?: string
  timeout_seconds?: number
}

export interface TemplateCreateRequest {
  name: string
  description: string
  template_type?: string
  roles?: Record<string, string>
  role_requirements?: Record<string, string[]>
  workflow: Record<string, unknown>
  max_participants?: number
  min_participants?: number
  tags?: string[]
}

export interface TemplateUpdateRequest {
  name?: string
  description?: string
  roles?: Record<string, string>
  workflow?: Record<string, unknown>
  tags?: string[]
}

export interface TaskRecommendRequest {
  required_capabilities: string[]
  min_match_score?: number
  max_results?: number
}

export const collaborationAPI = {
  getCapabilities: () => request.get('/agents/capabilities'),
  getAgentCapability: (agentId: string) => request.get(`/agents/capabilities/${agentId}`),
  registerCapability: (data: CapabilityRegistration) =>
    request.post('/agents/capabilities/register', data),
  unregisterCapability: (agentId: string) =>
    request.delete(`/agents/capabilities/${agentId}`),

  startCollaboration: (data: CollaborationRequest) =>
    request.post('/agents/collaborate', data),

  getTemplates: (params?: { template_type?: string; tags?: string }) =>
    request.get('/agents/templates', { params }),
  getPresetTemplates: () => request.get('/agents/templates/preset'),
  getTemplate: (templateId: string) => request.get(`/agents/templates/${templateId}`),
  createTemplate: (data: TemplateCreateRequest) =>
    request.post('/agents/templates', data),
  updateTemplate: (templateId: string, data: TemplateUpdateRequest) =>
    request.put(`/agents/templates/${templateId}`, data),
  deleteTemplate: (templateId: string) =>
    request.delete(`/agents/templates/${templateId}`),
  cloneTemplate: (templateId: string, newName?: string) =>
    request.post(`/agents/templates/${templateId}/clone`, null, { params: newName ? { new_name: newName } : undefined }),

  getRecommendations: (data: TaskRecommendRequest) =>
    request.post('/agents/recommend', data),
  getMatrix: () => request.get('/agents/matrix'),
  compareAgents: (agentIds: string[]) =>
    request.post('/agents/matrix/compare', null, { params: { agent_ids: agentIds.join(',') } }),

  getDlqStats: () => request.get('/agents/dlq/stats'),
  getDlqMessages: (params?: { reason?: string; limit?: number }) =>
    request.get('/agents/dlq/messages', { params }),
  retryDlqMessage: (messageId: string) =>
    request.post(`/agents/dlq/messages/${messageId}/retry`),
  discardDlqMessage: (messageId: string, reason?: string) =>
    request.delete(`/agents/dlq/messages/${messageId}`, { params: reason ? { reason } : undefined }),
}

