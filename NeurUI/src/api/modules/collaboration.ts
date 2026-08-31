import api from '@/api'
import type { ApiResponse } from '@/types/response'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface CollabSession {
  id: string
  name: string
  description: string
  status: string
  participants?: string[]
  createdAt: string
  completedAt?: string
}

export interface CollabTemplate {
  id: string
  name: string
  description: string
  type: string
  participants?: string[]
}

export interface CreateTemplatePayload {
  name: string
  description: string
  type: string
  participants?: string[]
}

export interface StartSessionPayload {
  templateId: string
  participants: string[]
  name: string
  description: string
}

export interface CollabStats {
  sessions: number
  templates: number
  workflows: number
  projects: number
}

export interface CanvasNodeSnapshot {
  id: string
  type: string
  label: string
  icon: string
  position: { x: number; y: number }
  inputs: { id: string; label: string }[]
  outputs: { id: string; label: string }[]
  config: Record<string, unknown>
}

/** 连线端点的语义引用（节点 + 端口）。旧快照可能只有坐标，故为可选。 */
export interface CanvasPortRef {
  nodeId: string
  portId: string
}

export interface CanvasEdgeSnapshot {
  id: string
  /** 起点：源节点的输出端口 */
  source?: CanvasPortRef
  /** 终点：目标节点的输入端口 */
  target?: CanvasPortRef
  x1: number
  y1: number
  x2: number
  y2: number
}

export interface CanvasSnapshot {
  id?: string
  name: string
  nodes: CanvasNodeSnapshot[]
  edges: CanvasEdgeSnapshot[]
  /** 乐观锁版本号（后端 CanvasStore 维护；保存时作为 base_version 回传） */
  version?: number
}

export interface SaveCanvasPayload {
  id?: string
  name: string
  nodes: CanvasNodeSnapshot[]
  edges: CanvasEdgeSnapshot[]
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

const BASE = '/collaboration'

/** List collaboration history sessions. */
export function listHistory() {
  return api.get<ApiResponse<CollabSession[]>>(`${BASE}/history`)
}

/** List active collaboration sessions. */
export function listSessions() {
  return api.get<ApiResponse<CollabSession[]>>(`${BASE}/sessions`)
}

/** List collaboration templates. */
export function listTemplates() {
  return api.get<ApiResponse<CollabTemplate[]>>(`${BASE}/templates`)
}

/** Create a new collaboration template. */
export function createTemplate(data: CreateTemplatePayload) {
  return api.post<ApiResponse<CollabTemplate>>(`${BASE}/templates`, data)
}

/** Update an existing collaboration template. */
export function updateTemplate(id: string, data: CreateTemplatePayload) {
  return api.put<ApiResponse<CollabTemplate>>(`${BASE}/templates/${id}`, data)
}

/** Delete a collaboration template. */
export function deleteTemplate(id: string) {
  return api.delete<ApiResponse<{ success: boolean }>>(`${BASE}/templates/${id}`)
}

/** Start a new collaboration session from a template. */
export function startSession(payload: StartSessionPayload) {
  return api.post<ApiResponse<CollabSession>>(`${BASE}/start`, payload)
}

/** Get collaboration overview stats. */
export function getCollabStats() {
  return api.get<ApiResponse<CollabStats>>(`${BASE}/stats`)
}

/** Save a canvas workflow (create). */
export function saveCanvas(payload: SaveCanvasPayload) {
  return api.post<ApiResponse<CanvasSnapshot>>(`${BASE}/canvas`, payload)
}

/** 画布摘要（列表用，不含节点大对象） */
export interface CanvasSummary {
  id: string
  name: string
  /** 画布归属项目（轻量项目脚手架：工作流=画布，可归属项目） */
  project_id?: string | null
  node_count: number
  edge_count: number
  created_at?: number
  updated_at?: number
}

/** List saved canvas summaries (newest first) — "我的画布"入口. */
export function listCanvases() {
  return api.get<ApiResponse<CanvasSummary[]>>(`${BASE}/canvas`)
}

/** 画布运行状态（节点级结果，供画布着色与输出查看） */
export interface CanvasRunStatus {
  run_id: string
  canvas_id: string
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled' | 'paused'
  node_results: Record<
    string,
    { status: string; output: unknown; error?: string | null; duration: number }
  >
  outputs: Record<string, unknown>
  error?: string | null
  duration?: number | null
}

/** Run a canvas workflow（session_id 可选：子 Agent 事件广播到该聊天会话）. */
export function runCanvas(
  canvasId: string,
  payload?: { session_id?: string; agent_id?: string; debug?: boolean; breakpoints?: string[] },
) {
  return api.post<ApiResponse<{ runId: string; status: string; workflow_id: string; debug?: boolean }>>(
    `${BASE}/canvas/${canvasId}/run`,
    payload ?? {},
  )
}

/** Natural language → canvas snapshot (R-8 对话式画布设计). */
export function canvasFromNl(prompt: string, agentId = 'default', model?: string) {
  return api.post<ApiResponse<{
    status: 'success' | 'failed'
    nodes?: CanvasNodeSnapshot[]
    edges?: CanvasEdgeSnapshot[]
    name?: string
    description?: string
    error?: string
  }>>(`${BASE}/canvas/from-nl`, { prompt, agent_id: agentId, model: model || undefined })
}

/** Poll a canvas run's execution status. */
export function getCanvasRun(canvasId: string, runId: string) {
  return api.get<ApiResponse<CanvasRunStatus>>(`${BASE}/canvas/${canvasId}/runs/${runId}`)
}

/** Get a canvas workflow by id. */
export function getCanvas(canvasId: string) {
  return api.get<ApiResponse<CanvasSnapshot>>(`${BASE}/canvas/${canvasId}`)
}

/** Update an existing canvas workflow.
 *
 * baseVersion：乐观锁。传入时若与服务端版本不一致，后端返回 409
 * （detail.current_version 为最新版本），调用方应重载后重试。
 */
export function updateCanvas(canvasId: string, payload: SaveCanvasPayload, baseVersion?: number) {
  return api.put<ApiResponse<CanvasSnapshot>>(`${BASE}/canvas/${canvasId}`, payload, {
    params: baseVersion != null ? { base_version: baseVersion } : undefined,
  })
}

/** Delete a canvas workflow. */
export function deleteCanvas(canvasId: string) {
  return api.delete<ApiResponse<{ id: string; deleted: boolean }>>(`${BASE}/canvas/${canvasId}`)
}

/** Import a ComfyUI workflow JSON as an editable canvas. */
export function importComfyuiCanvas(payload: {
  name: string
  description?: string
  workflow: Record<string, unknown>
}) {
  return api.post<ApiResponse<CanvasSnapshot>>(`${BASE}/comfyui/import-canvas`, payload)
}

// ---------------------------------------------------------------------------
// NeurFlow 调试与版本（P0/P2 前端集成）
// ---------------------------------------------------------------------------

const NF_BASE = '/neurflow'

/** 设置执行断点集合（replace=true 整体替换）。 */
export function setExecutionBreakpoints(
  executionId: string,
  breakpoints: string[],
  replace = true,
) {
  return api.post<ApiResponse<{ execution_id: string; breakpoints: string[]; count: number }>>(
    `${NF_BASE}/executions/${executionId}/breakpoint`,
    { breakpoints, replace },
  )
}

/** 恢复暂停中的执行（step: in/over/out 或省略）。 */
export function resumeExecution(executionId: string, step?: 'in' | 'over' | 'out') {
  return api.post<ApiResponse<{ execution_id: string; resumed: boolean; step_mode: string | null }>>(
    `${NF_BASE}/executions/${executionId}/resume`,
    step ? { step } : {},
  )
}

/** 获取执行实例当前变量（inputs/variables/node_results）。 */
export function getExecutionVariables(executionId: string) {
  return api.get<ApiResponse<Record<string, unknown>>>(
    `${NF_BASE}/executions/${executionId}/variables`,
  )
}

/** 设置节点 mock 输出（mockOutput=null 时清除）。 */
export function setNodeMock(nodeId: string, mockOutput: unknown) {
  return api.put<ApiResponse<{ node_id: string; mocked: boolean }>>(
    `${NF_BASE}/nodes/${nodeId}/mock`,
    { mock_output: mockOutput },
  )
}

/** 工作流版本历史（倒序）。 */
export function listWorkflowVersions(workflowId: string) {
  return api.get<ApiResponse<Array<{ version: number; snapshot_json: string; commit_msg: string; created_at: number }>>>(
    `${NF_BASE}/workflows/${workflowId}/versions`,
  )
}

/** 回滚工作流到指定版本。 */
export function rollbackWorkflowVersion(workflowId: string, version: number) {
  return api.post<ApiResponse<{ workflow: Record<string, unknown> }>>(
    `${NF_BASE}/workflows/${workflowId}/versions/${version}/rollback`,
  )
}

// ---------------------------------------------------------------------------
// NeurFlow 触发器（P1 前端集成）
// ---------------------------------------------------------------------------

export interface WorkflowTriggerSummary {
  id: string
  workflow_id: string
  type: 'webhook' | 'cron' | 'manual'
  enabled: boolean
  config: Record<string, unknown>
  rate_limit_per_minute: number | null
  created_at: number
}

export interface CreateTriggerResult {
  trigger: WorkflowTriggerSummary
  secret?: string
}

/** 列出工作流触发器。 */
export function listWorkflowTriggers(workflowId: string) {
  return api.get<ApiResponse<WorkflowTriggerSummary[]>>(
    `${NF_BASE}/workflows/${workflowId}/triggers`,
  )
}

/** 创建触发器（webhook 时响应含一次性明文 secret）。 */
export function createWorkflowTrigger(
  workflowId: string,
  payload: { type: string; config?: Record<string, unknown>; rate_limit_per_minute?: number },
) {
  return api.post<ApiResponse<CreateTriggerResult>>(
    `${NF_BASE}/workflows/${workflowId}/triggers`,
    payload,
  )
}

/** 删除触发器。 */
export function deleteWorkflowTrigger(triggerId: string) {
  return api.delete<ApiResponse<{ code: number }>>(`${NF_BASE}/triggers/${triggerId}`)
}

/** 手动触发（测试用）。 */
export function fireWorkflowTrigger(triggerId: string, inputs: Record<string, unknown> = {}) {
  return api.post<ApiResponse<Record<string, unknown>>>(
    `${NF_BASE}/triggers/${triggerId}/fire`,
    inputs,
  )
}

/** webhook 投递记录。 */
export function listTriggerDeliveries(triggerId: string, limit = 50) {
  return api.get<ApiResponse<Array<Record<string, unknown>>>>(
    `${NF_BASE}/triggers/${triggerId}/deliveries`,
    { params: { limit } },
  )
}
