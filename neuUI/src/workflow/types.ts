/**
 * Neurflow 前端类型定义
 * 基于 docs/neurflow-dev-spec.md 规范
 */

// ==================== 节点端口 ====================

export interface NodePort {
  id: string
  name: string
  type: 'string' | 'number' | 'boolean' | 'object' | 'array' | 'any'
  required?: boolean
  description?: string
  defaultValue?: any
}

// ==================== SubBlock 配置 ====================

export type SubBlockType =
  | 'input'
  | 'textarea'
  | 'select'
  | 'slider'
  | 'switch'
  | 'code'
  | 'json'
  | 'model-selector'
  | 'file'
  | 'number'
  | 'color'
  | 'date'
  | 'time'
  | 'datetime'
  | 'range'
  | 'checkbox'
  | 'radio'
  | 'autocomplete'
  | 'tree-select'
  | 'cascader'
  | 'transfer'
  | 'upload'

export interface SubBlockConfig {
  id: string
  title: string
  type: SubBlockType
  placeholder?: string
  description?: string
  required?: boolean
  defaultValue?: any
  options?: Array<{ label: string; value: any; disabled?: boolean }>
  min?: number
  max?: number
  step?: number
  language?: string
  providerCapability?: string
  fileTypes?: string[]
  condition?: {
    field: string
    operator: 'eq' | 'ne' | 'gt' | 'lt' | 'gte' | 'lte' | 'in' | 'nin' | 'contains' | 'startsWith' | 'endsWith'
    value: any
  }
  validation?: {
    pattern?: string
    message?: string
    validator?: (value: any) => boolean | string
  }
  group?: string
  order?: number
  disabled?: boolean
  hidden?: boolean
}

// ==================== 节点定义 ====================

export type NodeSource = 'tool' | 'skill' | 'mcp' | 'builtin'

export type NodeCategory =
  | 'input'
  | 'output'
  | 'llm'
  | 'tool'
  | 'skill'
  | 'control'
  | 'data'
  | 'memory'
  | 'evolution'
  | 'tdd'
  | 'media'
  | 'integration'
  | 'custom'

export interface NodeDefinition {
  type: string
  label: string
  icon: string
  category: NodeCategory
  description: string
  subBlocks: SubBlockConfig[]
  inputs: NodePort[]
  outputs: NodePort[]
  source: NodeSource
  tags: string[]
  version?: string
  author?: string
  deprecated?: boolean
  hidden?: boolean
  maxInstances?: number
  color?: string
  documentation?: string
  examples?: Array<{
    name: string
    description: string
    inputs: Record<string, any>
    outputs: Record<string, any>
  }>
}

// ==================== 工作流定义 ====================

export type WorkflowStatus = 'draft' | 'published' | 'archived'

export interface WorkflowVariable {
  name: string
  type: 'string' | 'number' | 'boolean' | 'object' | 'array'
  defaultValue?: any
  description?: string
  required?: boolean
  scope?: 'global' | 'local'
}

export interface WorkflowNode {
  id: string
  type: string
  label: string
  position: { x: number; y: number }
  data: Record<string, any>
  subBlocks?: Record<string, any>
  inputs?: Record<string, any>
  outputs?: Record<string, any>
  disabled?: boolean
  locked?: boolean
  notes?: string
}

export interface WorkflowEdge {
  id: string
  source: string
  target: string
  sourceHandle?: string
  targetHandle?: string
  type?: 'default' | 'smoothstep' | 'step' | 'bezier'
  animated?: boolean
  style?: Record<string, any>
  label?: string
  condition?: {
    field: string
    operator: string
    value: any
  }
  metadata?: Record<string, any>
}

export interface WorkflowDefinition {
  id: string
  name: string
  description?: string
  version: string
  nodes: WorkflowNode[]
  edges: WorkflowEdge[]
  variables: WorkflowVariable[]
  tags: string[]
  category: string
  author?: string
  createdAt: number
  updatedAt: number
  status: WorkflowStatus
  template: boolean
  public: boolean
  viewport?: {
    x: number
    y: number
    zoom: number
  }
  metadata?: Record<string, any>
}

// ==================== 执行相关 ====================

export type ExecutionStatus = 'pending' | 'running' | 'paused' | 'completed' | 'failed' | 'cancelled'

export type ExecutionEventType =
  | 'started'
  | 'node_started'
  | 'node_completed'
  | 'node_failed'
  | 'node_skipped'
  | 'paused'
  | 'resumed'
  | 'completed'
  | 'failed'
  | 'cancelled'
  | 'log'
  | 'warning'
  | 'error'

export interface ExecutionEvent {
  type: ExecutionEventType
  nodeId?: string
  timestamp: number
  data?: any
  message?: string
  level?: 'info' | 'warning' | 'error' | 'debug'
}

export interface ExecutionInstance {
  id: string
  workflowId: string
  status: ExecutionStatus
  startedAt: number
  finishedAt?: number
  duration?: number
  inputs: Record<string, any>
  outputs?: Record<string, any>
  error?: string
  events: ExecutionEvent[]
  nodeStates: Record<string, {
    status: 'pending' | 'running' | 'completed' | 'failed' | 'skipped'
    startedAt?: number
    finishedAt?: number
    inputs?: Record<string, any>
    outputs?: Record<string, any>
    error?: string
  }>
  metadata?: Record<string, any>
}

// ==================== 团队 Agent ====================

export type AgentRole = 'coder' | 'reviewer' | 'researcher' | 'writer' | 'analyst' | 'designer' | 'tester' | 'custom'

export type AgentStatus = 'active' | 'archived' | 'busy' | 'idle'

export interface TeamAgent {
  id: string
  name: string
  role: AgentRole
  config: Record<string, any>
  flowId?: string
  status: AgentStatus
  createdAt: number
  updatedAt?: number
  capabilities?: string[]
  metadata?: Record<string, any>
}

// ==================== 模板 ====================

export interface WorkflowTemplate {
  id: string
  name: string
  description?: string
  category: string
  workflowId: string
  author?: string
  createdAt: number
  updatedAt: number
  downloads?: number
  rating?: number
  tags: string[]
  public: boolean
  metadata?: Record<string, any>
}

// ==================== API 响应 ====================

export interface PaginatedResponse<T> {
  data: T[]
  total: number
  page: number
  pageSize: number
  hasMore: boolean
}

export interface ApiResponse<T = any> {
  success: boolean
  data?: T
  error?: string
  message?: string
  timestamp?: number
}

// ==================== 画布状态 ====================

export interface CanvasState {
  nodes: WorkflowNode[]
  edges: WorkflowEdge[]
  viewport: {
    x: number
    y: number
    zoom: number
  }
  selectedNodes: string[]
  selectedEdges: string[]
  clipboard?: {
    nodes: WorkflowNode[]
    edges: WorkflowEdge[]
  }
  history?: {
    past: Array<{ nodes: WorkflowNode[]; edges: WorkflowEdge[] }>
    future: Array<{ nodes: WorkflowNode[]; edges: WorkflowEdge[] }>
  }
}

// ==================== 节点注册表 ====================

export interface NodeRegistry {
  nodes: Map<string, NodeDefinition>
  categories: Map<string, NodeDefinition[]>
  register(definition: NodeDefinition): void
  unregister(type: string): void
  get(type: string): NodeDefinition | undefined
  getByCategory(category: string): NodeDefinition[]
  getBySource(source: NodeSource): NodeDefinition[]
  search(query: string): NodeDefinition[]
  getAll(): NodeDefinition[]
  clear(): void
}

// ==================== 事件系统 ====================

export type WorkflowEventType =
  | 'node:add'
  | 'node:remove'
  | 'node:update'
  | 'node:select'
  | 'node:deselect'
  | 'edge:add'
  | 'edge:remove'
  | 'edge:update'
  | 'canvas:zoom'
  | 'canvas:pan'
  | 'canvas:fit'
  | 'workflow:save'
  | 'workflow:load'
  | 'workflow:execute'
  | 'workflow:cancel'
  | 'workflow:validate'
  | 'workflow:publish'
  | 'execution:start'
  | 'execution:pause'
  | 'execution:resume'
  | 'execution:cancel'
  | 'execution:complete'
  | 'execution:error'

export interface WorkflowEvent {
  type: WorkflowEventType
  payload?: any
  timestamp: number
  source?: string
}

// ==================== 工具函数类型 ====================

export type NodeFactory = (position: { x: number; y: number }, data?: Record<string, any>) => WorkflowNode

export type EdgeFactory = (source: string, target: string, sourceHandle?: string, targetHandle?: string) => WorkflowEdge

export type Validator = (workflow: WorkflowDefinition) => ValidationResult

export interface ValidationResult {
  valid: boolean
  errors: ValidationError[]
  warnings: ValidationError[]
}

export interface ValidationError {
  type: 'error' | 'warning'
  nodeId?: string
  edgeId?: string
  message: string
  code?: string
  severity?: 'critical' | 'major' | 'minor'
}

// ==================== 配置 ====================

export interface WorkflowConfig {
  autoSave: boolean
  autoSaveInterval: number
  snapToGrid: boolean
  gridSize: number
  showGrid: boolean
  showMinimap: boolean
  showControls: boolean
  showBackground: boolean
  enableAnimations: boolean
  enableHistory: boolean
  maxHistorySize: number
  enableClipboard: boolean
  enableKeyboardShortcuts: boolean
  theme: 'light' | 'dark' | 'auto'
  language: string
  debug: boolean
}

// ==================== 序列化 ====================

export interface SerializedWorkflow {
  version: string
  format: string
  timestamp: number
  workflow: {
    id?: string
    name: string
    description?: string
    category?: string
    status?: string
    version?: string
    tags?: string[]
    nodes: any[]
    edges: any[]
    variables?: WorkflowVariable[]
  }
  metadata?: {
    author?: string
    createdAt?: number
    updatedAt?: number
    nodeCount?: number
    edgeCount?: number
  }
}

// ==================== 导出 ====================

export default {
  // 类型定义已在上面导出
}
