import api from '@/api'
import type { ApiResponse } from '@/types/response'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface WorkflowNode {
  id: string
  type: string
  label: string
  position: { x: number; y: number }
  config: Record<string, unknown>
}

export interface WorkflowEdge {
  id: string
  source: string
  target: string
  label?: string
}

export interface WorkflowVariable {
  name: string
  type: string
  default_value?: unknown
  description?: string
}

export interface WorkflowDefinition {
  id: string
  name: string
  description: string
  version: string
  nodes: WorkflowNode[]
  edges: WorkflowEdge[]
  variables: WorkflowVariable[]
  tags: string[]
  category: string
  author: string
  created_at: number
  updated_at: number
  status: string
  template: boolean
  public: boolean
  metadata: Record<string, unknown>
}

export interface WorkflowExecution {
  id: string
  workflow_id: string
  status: string
  inputs: Record<string, unknown>
  outputs: Record<string, unknown>
  node_results: Record<string, unknown>
  variables: Record<string, unknown>
  started_at: number
  finished_at?: number
  duration?: number
  error?: string
}

export interface SubBlockDef {
  /** 配置项 ID（兼容后端 name 键） */
  id: string
  /** 显示标题（兼容后端 label 键） */
  title: string
  /** input | textarea | select | slider | json | code | file ... */
  type: string
  required?: boolean
  default_value?: unknown
  options?: Array<{ label: string; value: string } | string>
  placeholder?: string
  description?: string
  min?: number
  max?: number
  language?: string
}

export interface NodePortDef {
  id: string
  label: string
}

export interface NodeDefinition {
  type: string
  label: string
  icon: string
  category: string
  description: string
  source: string
  version?: string
  tags?: string[]
  /** 配置表单（画布动态节点库渲染 select/slider/textarea 等） */
  sub_blocks?: SubBlockDef[]
  inputs?: NodePortDef[]
  outputs?: NodePortDef[]
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

const BASE = '/neurflow'

// --- Workflows CRUD ---

/** List workflows. */
export function getWorkflows(params?: { category?: string; status?: string; limit?: number; offset?: number }) {
  return api.get<ApiResponse<{ workflows: WorkflowDefinition[]; total: number }>>(`${BASE}/workflows`, { params })
}

/** Create a workflow. */
export function createWorkflow(data: Partial<WorkflowDefinition>) {
  return api.post<ApiResponse<{ workflow: WorkflowDefinition; message: string }>>(`${BASE}/workflows`, data)
}

/** Get workflow details. */
export function getWorkflow(workflowId: string) {
  return api.get<ApiResponse<{ workflow: WorkflowDefinition }>>(`${BASE}/workflows/${workflowId}`)
}

/** Update a workflow. */
export function updateWorkflow(workflowId: string, data: Partial<WorkflowDefinition>) {
  return api.put<ApiResponse<{ workflow: WorkflowDefinition; message: string }>>(`${BASE}/workflows/${workflowId}`, data)
}

/** Delete a workflow. */
export function deleteWorkflow(workflowId: string) {
  return api.delete<ApiResponse<{ message: string }>>(`${BASE}/workflows/${workflowId}`)
}

/** Search workflows. */
export function searchWorkflows(query: string) {
  return api.get<ApiResponse<{ workflows: WorkflowDefinition[]; total: number }>>(`${BASE}/workflows/search/${query}`)
}

// --- Validation ---

/** Validate a workflow. */
export function validateWorkflow(workflowId: string) {
  return api.post<ApiResponse<{ is_valid: boolean; has_cycle: boolean; has_start: boolean; has_end: boolean; errors: string[]; warnings: string[] }>>(`${BASE}/workflows/${workflowId}/validate`)
}

// --- Execution ---

/** Execute a workflow. */
export function executeWorkflow(workflowId: string, inputs: Record<string, unknown> = {}, options?: { user_id?: string; agent_id?: string }) {
  return api.post<ApiResponse<{ instance: WorkflowExecution }>>(`${BASE}/workflows/${workflowId}/execute`, { inputs, ...options })
}

/** List executions. */
export function getExecutions(params?: { workflow_id?: string; status?: string; limit?: number; offset?: number }) {
  return api.get<ApiResponse<{ executions: Pick<WorkflowExecution, 'id' | 'workflow_id' | 'status' | 'started_at' | 'finished_at' | 'duration' | 'error'>[] }>>(`${BASE}/executions`, { params })
}

/** Get execution details. */
export function getExecution(executionId: string) {
  return api.get<ApiResponse<{ execution: WorkflowExecution }>>(`${BASE}/executions/${executionId}`)
}

/** Cancel execution. */
export function cancelExecution(executionId: string) {
  return api.post<ApiResponse<{ message: string }>>(`${BASE}/executions/${executionId}/cancel`)
}

/** Resume execution. */
export function resumeExecution(executionId: string) {
  return api.post<ApiResponse<{ message: string }>>(`${BASE}/executions/${executionId}/resume`)
}

// --- Extensions ---

/** Duplicate a workflow. */
export function duplicateWorkflow(workflowId: string) {
  return api.post<ApiResponse<{ workflow: WorkflowDefinition; message: string }>>(`${BASE}/workflows/${workflowId}/duplicate`)
}

/** Publish a workflow. */
export function publishWorkflow(workflowId: string) {
  return api.post<ApiResponse<{ message: string; workflow: WorkflowDefinition }>>(`${BASE}/workflows/${workflowId}/publish`)
}

// --- Nodes ---

/** List all registered nodes. */
export function getNodes(params?: { category?: string; source?: string }) {
  return api.get<ApiResponse<{ nodes: NodeDefinition[]; total: number }>>(`${BASE}/nodes`, { params })
}

/** Search nodes. */
export function searchNodes(query: string) {
  return api.get<ApiResponse<{ nodes: NodeDefinition[]; total: number }>>(`${BASE}/nodes/search/${query}`)
}

/** Sync all nodes. */
export function syncNodes() {
  return api.post<ApiResponse<{ sync_result: unknown; message: string }>>(`${BASE}/nodes/sync`)
}

/** Get node statistics. */
export function getNodeStats() {
  return api.get<ApiResponse<{ summary: unknown }>>(`${BASE}/nodes/stats`)
}

// --- Templates ---

/** List workflow templates. */
export function getTemplates(params?: { category?: string }) {
  return api.get<ApiResponse<{ templates: WorkflowDefinition[]; total: number }>>(`${BASE}/templates`, { params })
}

/** Create template from a workflow. */
export function createTemplate(data: { workflow_id: string; name?: string; description?: string; category?: string }) {
  return api.post<ApiResponse<{ template: WorkflowDefinition; message: string }>>(`${BASE}/templates`, data)
}

/** Instantiate a workflow from a template. */
export function instantiateTemplate(templateId: string, data: { name?: string; variables?: Record<string, unknown> }) {
  return api.post<ApiResponse<{ workflow: WorkflowDefinition; message: string }>>(`${BASE}/templates/${templateId}/instantiate`, data)
}

// --- Stats ---

/** Get Neurflow statistics. */
export function getNeurflowStats() {
  return api.get<ApiResponse<{ storage: unknown; nodes: unknown }>>(`${BASE}/stats`)
}

// --- ComfyUI 整合（Infinite-Canvas） ---

/** ComfyUI 服务状态。 */
export interface ComfyuiStatus {
  available: boolean
  host: string | null
}

/** ComfyUI 节点执行结果。 */
export interface ComfyuiExecuteResult {
  status: 'success' | 'failed'
  output: Record<string, unknown> | null
  error: string | null
}

/** 导入 ComfyUI API 格式工作流为 Neurflow WorkflowDefinition。 */
export function importComfyuiWorkflow(data: {
  name: string
  description?: string
  workflow: Record<string, unknown>
}) {
  return api.post<ApiResponse<{ workflow: WorkflowDefinition; message: string }>>(
    `${BASE}/comfyui/import`,
    data,
  )
}

/** 检查 ComfyUI 服务可用性。 */
export function getComfyuiStatus() {
  return api.get<ApiResponse<ComfyuiStatus>>(`${BASE}/comfyui/status`)
}

/** 直接执行单个 ComfyUI 节点。 */
export function executeComfyuiNode(data: {
  class_type: string
  config?: Record<string, unknown>
  inputs?: Record<string, unknown>
}) {
  return api.post<ComfyuiExecuteResult>(`${BASE}/comfyui/execute`, data)
}
