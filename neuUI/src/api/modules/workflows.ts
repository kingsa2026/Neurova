import { request } from '@/api'
import type { UnknownRecord, WorkflowStep } from '@/types/api'

// 工作流需要 project_id，使用默认项目
const defaultProject = 'default'

export interface WorkflowStepCreate {
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
}

export interface WorkflowStepUpdate {
  name?: string
  description?: string
  agent_id?: string
  skills?: string[]
  prompt_template?: string
  position_x?: number
  position_y?: number
  on_success?: string
  on_failure?: string
  timeout?: number
}

export interface StepPositionUpdate {
  step_id: string
  position_x: number
  position_y: number
}

export interface WorkflowCreate {
  workflow_id: string
  name: string
  description?: string
  trigger_type?: string
  trigger_config?: UnknownRecord
  steps?: WorkflowStep[]
}

export interface WorkflowUpdate {
  name?: string
  description?: string
  trigger_type?: string
  trigger_config?: UnknownRecord
  steps?: WorkflowStep[]
  is_active?: boolean
}

export const workflowAPI = {
  list: (projectId = defaultProject) => request.get(`/projects/${projectId}/workflows`),
  create: (data: WorkflowCreate, projectId = defaultProject) =>
    request.post(`/projects/${projectId}/workflows`, data),
  get: (id: string, projectId = defaultProject) =>
    request.get(`/projects/${projectId}/workflows/${id}`),
  update: (id: string, data: WorkflowUpdate, projectId = defaultProject) =>
    request.put(`/projects/${projectId}/workflows/${id}`, data),
  delete: (id: string, projectId = defaultProject) =>
    request.delete(`/projects/${projectId}/workflows/${id}`),
  execute: (id: string, context: UnknownRecord = {}, projectId = defaultProject) =>
    request.post(`/projects/${projectId}/workflows/${id}/execute`, { context }),

  listExecutions: (id: string, projectId = defaultProject) =>
    request.get(`/projects/${projectId}/workflows/${id}/executions`),
  getExecution: (id: string, executionId: string, projectId = defaultProject) =>
    request.get(`/projects/${projectId}/workflows/${id}/executions/${executionId}`),
  pauseExecution: (id: string, executionId: string, projectId = defaultProject) =>
    request.post(`/projects/${projectId}/workflows/${id}/executions/${executionId}/pause`),
  resumeExecution: (id: string, executionId: string, projectId = defaultProject) =>
    request.post(`/projects/${projectId}/workflows/${id}/executions/${executionId}/resume`),
  cancelExecution: (id: string, executionId: string, projectId = defaultProject) =>
    request.post(`/projects/${projectId}/workflows/${id}/executions/${executionId}/cancel`),

  generate: (data: { description: string; team_id?: string; available_agents?: string[]; available_skills?: string[] }, projectId = defaultProject) =>
    request.post(`/projects/${projectId}/workflows/generate`, data),
  generateAndSave: (data: { description: string; team_id?: string; available_agents?: string[]; available_skills?: string[] }, projectId = defaultProject) =>
    request.post(`/projects/${projectId}/workflows/generate-and-save`, data),

  getNodes: (id: string, projectId = defaultProject) =>
    request.get(`/projects/${projectId}/workflows/${id}/nodes`),

  addStep: (id: string, data: WorkflowStepCreate, projectId = defaultProject) =>
    request.post(`/projects/${projectId}/workflows/${id}/steps`, data),
  updateStep: (id: string, stepId: string, data: WorkflowStepUpdate, projectId = defaultProject) =>
    request.put(`/projects/${projectId}/workflows/${id}/steps/${stepId}`, data),
  removeStep: (id: string, stepId: string, projectId = defaultProject) =>
    request.delete(`/projects/${projectId}/workflows/${id}/steps/${stepId}`),

  updateStepPosition: (id: string, data: StepPositionUpdate, projectId = defaultProject) =>
    request.put(`/projects/${projectId}/workflows/${id}/steps/${data.step_id}/position`, data),
  batchUpdateSteps: (id: string, steps: StepPositionUpdate[], projectId = defaultProject) =>
    request.put(`/projects/${projectId}/workflows/${id}/steps/batch-update`, { steps }),

  createEdge: (id: string, data: { source_step_id: string; target_step_id: string; edge_type?: string; label?: string }, projectId = defaultProject) =>
    request.post(`/projects/${projectId}/workflows/${id}/edges`, data),
  deleteEdge: (id: string, sourceStepId: string, targetStepId: string, projectId = defaultProject) =>
    request.delete(`/projects/${projectId}/workflows/${id}/edges/${sourceStepId}/${targetStepId}`),
  updateEdge: (id: string, sourceStepId: string, targetStepId: string, data: { edge_type?: string; label?: string }, projectId = defaultProject) =>
    request.put(`/projects/${projectId}/workflows/${id}/edges/${sourceStepId}/${targetStepId}`, data),

  getViewport: (id: string, projectId = defaultProject) =>
    request.get(`/projects/${projectId}/workflows/${id}/viewport`),
  updateViewport: (id: string, data: { zoom?: number; offset_x?: number; offset_y?: number }, projectId = defaultProject) =>
    request.put(`/projects/${projectId}/workflows/${id}/viewport`, data),
}
