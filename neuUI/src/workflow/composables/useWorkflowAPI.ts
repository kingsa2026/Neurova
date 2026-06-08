/**
 * Neurflow API 组合式函数
 * 封装所有工作流相关的 API 调用
 */

import { ref, reactive, computed } from 'vue'
import type {
  WorkflowDefinition,
  WorkflowNode,
  WorkflowEdge,
  ExecutionInstance,
  NodeDefinition,
  TeamAgent,
  WorkflowTemplate,
  ValidationResult,
  WorkflowConfig
} from '../types'

// API 基础配置
const API_BASE = '/api/v1/neurflow'

// 通用请求工具
async function request<T>(
  url: string,
  options: RequestInit = {}
): Promise<T> {
  const response = await fetch(`${API_BASE}${url}`, {
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
    ...options,
  })

  if (!response.ok) {
    const error = await response.json().catch(() => ({}))
    throw new Error(error.detail || `HTTP ${response.status}`)
  }

  return response.json()
}

// ==================== 工作流 CRUD ====================

export function useWorkflows() {
  const workflows = ref<WorkflowDefinition[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  const total = computed(() => workflows.value.length)

  async function fetchWorkflows(params?: {
    category?: string
    status?: string
    limit?: number
    offset?: number
  }) {
    loading.value = true
    error.value = null

    try {
      const queryParams = new URLSearchParams()
      if (params?.category) queryParams.append('category', params.category)
      if (params?.status) queryParams.append('status', params.status)
      if (params?.limit) queryParams.append('limit', params.limit.toString())
      if (params?.offset) queryParams.append('offset', params.offset.toString())

      const query = queryParams.toString()
      const url = `/workflows${query ? `?${query}` : ''}`
      const data = await request<{ workflows: WorkflowDefinition[]; total: number }>(url)
      
      workflows.value = data.workflows
      return data
    } catch (err) {
      error.value = err instanceof Error ? err.message : 'Failed to fetch workflows'
      throw err
    } finally {
      loading.value = false
    }
  }

  async function getWorkflow(id: string) {
    return request<WorkflowDefinition>(`/workflows/${id}`)
  }

  async function createWorkflow(workflow: Partial<WorkflowDefinition>) {
    return request<WorkflowDefinition>('/workflows', {
      method: 'POST',
      body: JSON.stringify(workflow),
    })
  }

  async function updateWorkflow(id: string, updates: Partial<WorkflowDefinition>) {
    return request<WorkflowDefinition>(`/workflows/${id}`, {
      method: 'PUT',
      body: JSON.stringify(updates),
    })
  }

  async function deleteWorkflow(id: string) {
    return request<void>(`/workflows/${id}`, {
      method: 'DELETE',
    })
  }

  return {
    workflows,
    loading,
    error,
    total,
    fetchWorkflows,
    getWorkflow,
    createWorkflow,
    updateWorkflow,
    deleteWorkflow,
  }
}

// ==================== 工作流定义 ====================

export function useWorkflowDefinition() {
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function getDefinition(id: string) {
    loading.value = true
    error.value = null

    try {
      return await request<WorkflowDefinition>(`/workflows/${id}/definition`)
    } catch (err) {
      error.value = err instanceof Error ? err.message : 'Failed to fetch definition'
      throw err
    } finally {
      loading.value = false
    }
  }

  async function saveDefinition(id: string, definition: Partial<WorkflowDefinition>) {
    loading.value = true
    error.value = null

    try {
      return await request<WorkflowDefinition>(`/workflows/${id}/definition`, {
        method: 'PUT',
        body: JSON.stringify(definition),
      })
    } catch (err) {
      error.value = err instanceof Error ? err.message : 'Failed to save definition'
      throw err
    } finally {
      loading.value = false
    }
  }

  async function validate(id: string) {
    return request<ValidationResult>(`/workflows/${id}/validate`, {
      method: 'POST',
    })
  }

  return {
    loading,
    error,
    getDefinition,
    saveDefinition,
    validate,
  }
}

// ==================== 执行 ====================

export function useExecution() {
  const executions = ref<ExecutionInstance[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function startExecution(workflowId: string, input?: Record<string, any>) {
    loading.value = true
    error.value = null

    try {
      return await request<ExecutionInstance>(`/workflows/${workflowId}/execute`, {
        method: 'POST',
        body: JSON.stringify({ input }),
      })
    } catch (err) {
      error.value = err instanceof Error ? err.message : 'Failed to start execution'
      throw err
    } finally {
      loading.value = false
    }
  }

  async function getExecution(executionId: string) {
    return request<ExecutionInstance>(`/executions/${executionId}`)
  }

  async function pauseExecution(executionId: string) {
    return request<void>(`/executions/${executionId}/pause`, {
      method: 'POST',
    })
  }

  async function resumeExecution(executionId: string) {
    return request<void>(`/executions/${executionId}/resume`, {
      method: 'POST',
    })
  }

  async function cancelExecution(executionId: string) {
    return request<void>(`/executions/${executionId}/cancel`, {
      method: 'POST',
    })
  }

  async function getExecutionLogs(executionId: string) {
    return request<{ logs: any[] }>(`/executions/${executionId}/logs`)
  }

  async function listExecutions(workflowId?: string, limit = 50) {
    const params = new URLSearchParams()
    if (workflowId) params.append('workflow_id', workflowId)
    params.append('limit', limit.toString())

    const query = params.toString()
    const url = `/executions${query ? `?${query}` : ''}`
    const data = await request<{ executions: ExecutionInstance[] }>(url)
    
    executions.value = data.executions
    return data
  }

  return {
    executions,
    loading,
    error,
    startExecution,
    getExecution,
    pauseExecution,
    resumeExecution,
    cancelExecution,
    getExecutionLogs,
    listExecutions,
  }
}

// ==================== 节点注册 ====================

export function useNodeRegistry() {
  const nodes = ref<NodeDefinition[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  const categories = computed(() => {
    const cats = new Set(nodes.value.map(n => n.category))
    return Array.from(cats).sort()
  })

  const nodesByCategory = computed(() => {
    const map: Record<string, NodeDefinition[]> = {}
    for (const node of nodes.value) {
      if (!map[node.category]) map[node.category] = []
      map[node.category].push(node)
    }
    return map
  })

  async function fetchNodes(params?: {
    category?: string
    source?: string
    search?: string
  }) {
    loading.value = true
    error.value = null

    try {
      const queryParams = new URLSearchParams()
      if (params?.category) queryParams.append('category', params.category)
      if (params?.source) queryParams.append('source', params.source)
      if (params?.search) queryParams.append('search', params.search)

      const query = queryParams.toString()
      const url = `/nodes${query ? `?${query}` : ''}`
      const data = await request<{ nodes: NodeDefinition[] }>(url)
      
      nodes.value = data.nodes
      return data
    } catch (err) {
      error.value = err instanceof Error ? err.message : 'Failed to fetch nodes'
      throw err
    } finally {
      loading.value = false
    }
  }

  async function getNode(type: string) {
    return request<NodeDefinition>(`/nodes/${type}`)
  }

  async function refreshNodes() {
    return request<{ added: number; removed: number }>('/nodes/refresh', {
      method: 'POST',
    })
  }

  return {
    nodes,
    loading,
    error,
    categories,
    nodesByCategory,
    fetchNodes,
    getNode,
    refreshNodes,
  }
}

// ==================== Agent 管理 ====================

export function useAgents() {
  const agents = ref<TeamAgent[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function fetchAgents() {
    loading.value = true
    error.value = null

    try {
      const data = await request<{ agents: TeamAgent[] }>('/agents')
      agents.value = data.agents
      return data
    } catch (err) {
      error.value = err instanceof Error ? err.message : 'Failed to fetch agents'
      throw err
    } finally {
      loading.value = false
    }
  }

  async function createAgent(agent: Partial<TeamAgent>) {
    return request<TeamAgent>('/agents', {
      method: 'POST',
      body: JSON.stringify(agent),
    })
  }

  async function updateAgent(id: string, updates: Partial<TeamAgent>) {
    return request<TeamAgent>(`/agents/${id}`, {
      method: 'PUT',
      body: JSON.stringify(updates),
    })
  }

  async function deleteAgent(id: string) {
    return request<void>(`/agents/${id}`, {
      method: 'DELETE',
    })
  }

  return {
    agents,
    loading,
    error,
    fetchAgents,
    createAgent,
    updateAgent,
    deleteAgent,
  }
}

// ==================== 模板 ====================

export function useTemplates() {
  const templates = ref<WorkflowTemplate[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function fetchTemplates(category?: string) {
    loading.value = true
    error.value = null

    try {
      const params = new URLSearchParams()
      if (category) params.append('category', category)

      const query = params.toString()
      const url = `/templates${query ? `?${query}` : ''}`
      const data = await request<{ templates: WorkflowTemplate[] }>(url)
      
      templates.value = data.templates
      return data
    } catch (err) {
      error.value = err instanceof Error ? err.message : 'Failed to fetch templates'
      throw err
    } finally {
      loading.value = false
    }
  }

  async function getTemplate(id: string) {
    return request<WorkflowTemplate>(`/templates/${id}`)
  }

  async function createFromTemplate(templateId: string, name?: string) {
    return request<WorkflowDefinition>('/templates/create', {
      method: 'POST',
      body: JSON.stringify({ template_id: templateId, name }),
    })
  }

  return {
    templates,
    loading,
    error,
    fetchTemplates,
    getTemplate,
    createFromTemplate,
  }
}

// ==================== 统一 API 接口 ====================

export function useNeurflowAPI() {
  const workflows = useWorkflows()
  const definition = useWorkflowDefinition()
  const execution = useExecution()
  const nodeRegistry = useNodeRegistry()
  const agents = useAgents()
  const templates = useTemplates()

  return {
    workflows,
    definition,
    execution,
    nodeRegistry,
    agents,
    templates,
  }
}