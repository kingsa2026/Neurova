/**
 * Neurflow 工作流状态管理
 * 使用 Pinia 管理工作流状态
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type {
  WorkflowDefinition,
  WorkflowNode,
  WorkflowEdge,
  ExecutionInstance,
  TeamAgent,
  WorkflowTemplate,
  ValidationResult,
  CanvasState,
} from '../types'
import { nodeRegistry } from '../registry'

// ==================== 工作流 Store ====================

export const useWorkflowStore = defineStore('workflow', () => {
  // ==================== 状态 ====================
  
  // 当前工作流
  const currentWorkflow = ref<WorkflowDefinition | null>(null)
  
  // 工作流列表
  const workflows = ref<WorkflowDefinition[]>([])
  
  // 执行实例
  const executions = ref<ExecutionInstance[]>([])
  const currentExecution = ref<ExecutionInstance | null>(null)
  
  // 团队 Agent
  const agents = ref<TeamAgent[]>([])
  
  // 模板
  const templates = ref<WorkflowTemplate[]>([])
  
  // 画布状态
  const canvasState = ref<CanvasState>({
    nodes: [],
    edges: [],
    viewport: { x: 0, y: 0, zoom: 1 },
    selectedNodes: [],
    selectedEdges: [],
  })
  
  // 加载状态
  const loading = ref(false)
  const error = ref<string | null>(null)
  
  // 节点注册表已加载
  const nodesLoaded = ref(false)
  
  // ==================== 计算属性 ====================
  
  /**
   * 当前工作流节点
   */
  const currentNodes = computed(() => {
    return currentWorkflow.value?.nodes || canvasState.value.nodes
  })
  
  /**
   * 当前工作流边
   */
  const currentEdges = computed(() => {
    return currentWorkflow.value?.edges || canvasState.value.edges
  })
  
  /**
   * 是否有选中节点
   */
  const hasSelection = computed(() => {
    return canvasState.value.selectedNodes.length > 0 || canvasState.value.selectedEdges.length > 0
  })
  
  /**
   * 选中的节点
   */
  const selectedNodes = computed(() => {
    return currentNodes.value.filter(n => 
      canvasState.value.selectedNodes.includes(n.id)
    )
  })
  
  /**
   * 选中的边
   */
  const selectedEdges = computed(() => {
    return currentEdges.value.filter(e => 
      canvasState.value.selectedEdges.includes(e.id)
    )
  })
  
  /**
   * 活跃的执行实例
   */
  const activeExecutions = computed(() => {
    return executions.value.filter(e => 
      e.status === 'running' || e.status === 'paused'
    )
  })
  
  /**
   * 活跃的 Agent
   */
  const activeAgents = computed(() => {
    return agents.value.filter(a => a.status === 'active')
  })
  
  // ==================== 操作 ====================
  
  /**
   * 加载节点定义
   */
  async function loadNodeDefinitions() {
    try {
      const { initializeNodeRegistry } = await import('../registry')
      await initializeNodeRegistry()
      nodesLoaded.value = true
    } catch (err) {
      console.error('Failed to load node definitions:', err)
      error.value = '加载节点定义失败'
    }
  }
  
  /**
   * 加载工作流列表
   */
  async function loadWorkflows(params?: {
    page?: number
    pageSize?: number
    category?: string
    status?: string
  }) {
    loading.value = true
    error.value = null
    
    try {
      const { getWorkflows } = await import('../api/workflows')
      const response = await getWorkflows(params)
      workflows.value = response.data
      return response
    } catch (err) {
      error.value = '加载工作流列表失败'
      throw err
    } finally {
      loading.value = false
    }
  }
  
  /**
   * 加载单个工作流
   */
  async function loadWorkflow(id: string) {
    loading.value = true
    error.value = null
    
    try {
      const { getWorkflow } = await import('../api/workflows')
      const workflow = await getWorkflow(id)
      currentWorkflow.value = workflow
      canvasState.value.nodes = workflow.nodes
      canvasState.value.edges = workflow.edges
      return workflow
    } catch (err) {
      error.value = '加载工作流失败'
      throw err
    } finally {
      loading.value = false
    }
  }
  
  /**
   * 创建工作流
   */
  async function createWorkflow(data: Partial<WorkflowDefinition>) {
    loading.value = true
    error.value = null
    
    try {
      const { createWorkflow } = await import('../api/workflows')
      const workflow = await createWorkflow(data)
      workflows.value.unshift(workflow)
      currentWorkflow.value = workflow
      return workflow
    } catch (err) {
      error.value = '创建工作流失败'
      throw err
    } finally {
      loading.value = false
    }
  }
  
  /**
   * 更新工作流
   */
  async function updateWorkflow(id: string, data: Partial<WorkflowDefinition>) {
    loading.value = true
    error.value = null
    
    try {
      const { updateWorkflow } = await import('../api/workflows')
      const workflow = await updateWorkflow(id, data)
      
      // 更新列表
      const index = workflows.value.findIndex(w => w.id === id)
      if (index >= 0) {
        workflows.value[index] = workflow
      }
      
      // 更新当前工作流
      if (currentWorkflow.value?.id === id) {
        currentWorkflow.value = workflow
      }
      
      return workflow
    } catch (err) {
      error.value = '更新工作流失败'
      throw err
    } finally {
      loading.value = false
    }
  }
  
  /**
   * 删除工作流
   */
  async function deleteWorkflow(id: string) {
    loading.value = true
    error.value = null
    
    try {
      const { deleteWorkflow } = await import('../api/workflows')
      await deleteWorkflow(id)
      
      // 从列表移除
      workflows.value = workflows.value.filter(w => w.id !== id)
      
      // 清除当前工作流
      if (currentWorkflow.value?.id === id) {
        currentWorkflow.value = null
      }
    } catch (err) {
      error.value = '删除工作流失败'
      throw err
    } finally {
      loading.value = false
    }
  }
  
  /**
   * 保存画布状态
   */
  async function saveCanvasState(workflowId: string) {
    if (!currentWorkflow.value) return
    
    try {
      const { updateWorkflowDefinition } = await import('../api/workflows')
      await updateWorkflowDefinition(workflowId, {
        nodes: canvasState.value.nodes,
        edges: canvasState.value.edges,
        variables: currentWorkflow.value.variables,
      })
    } catch (err) {
      console.error('Failed to save canvas state:', err)
    }
  }
  
  /**
   * 更新节点
   */
  function updateNodes(nodes: WorkflowNode[]) {
    canvasState.value.nodes = nodes
    if (currentWorkflow.value) {
      currentWorkflow.value.nodes = nodes
    }
  }
  
  /**
   * 更新边
   */
  function updateEdges(edges: WorkflowEdge[]) {
    canvasState.value.edges = edges
    if (currentWorkflow.value) {
      currentWorkflow.value.edges = edges
    }
  }
  
  /**
   * 添加节点
   */
  function addNode(node: WorkflowNode) {
    canvasState.value.nodes.push(node)
    if (currentWorkflow.value) {
      currentWorkflow.value.nodes.push(node)
    }
  }
  
  /**
   * 删除节点
   */
  function removeNode(nodeId: string) {
    canvasState.value.nodes = canvasState.value.nodes.filter(n => n.id !== nodeId)
    canvasState.value.edges = canvasState.value.edges.filter(e => 
      e.source !== nodeId && e.target !== nodeId
    )
    
    if (currentWorkflow.value) {
      currentWorkflow.value.nodes = currentWorkflow.value.nodes.filter(n => n.id !== nodeId)
      currentWorkflow.value.edges = currentWorkflow.value.edges.filter(e => 
        e.source !== nodeId && e.target !== nodeId
      )
    }
    
    // 清除选中状态
    canvasState.value.selectedNodes = canvasState.value.selectedNodes.filter(id => id !== nodeId)
  }
  
  /**
   * 添加边
   */
  function addEdge(edge: WorkflowEdge) {
    canvasState.value.edges.push(edge)
    if (currentWorkflow.value) {
      currentWorkflow.value.edges.push(edge)
    }
  }
  
  /**
   * 删除边
   */
  function removeEdge(edgeId: string) {
    canvasState.value.edges = canvasState.value.edges.filter(e => e.id !== edgeId)
    if (currentWorkflow.value) {
      currentWorkflow.value.edges = currentWorkflow.value.edges.filter(e => e.id !== edgeId)
    }
    
    // 清除选中状态
    canvasState.value.selectedEdges = canvasState.value.selectedEdges.filter(id => id !== edgeId)
  }
  
  /**
   * 选择节点
   */
  function selectNode(nodeId: string, multi = false) {
    if (multi) {
      if (!canvasState.value.selectedNodes.includes(nodeId)) {
        canvasState.value.selectedNodes.push(nodeId)
      }
    } else {
      canvasState.value.selectedNodes = [nodeId]
      canvasState.value.selectedEdges = []
    }
  }
  
  /**
   * 选择边
   */
  function selectEdge(edgeId: string, multi = false) {
    if (multi) {
      if (!canvasState.value.selectedEdges.includes(edgeId)) {
        canvasState.value.selectedEdges.push(edgeId)
      }
    } else {
      canvasState.value.selectedEdges = [edgeId]
      canvasState.value.selectedNodes = []
    }
  }
  
  /**
   * 清除选择
   */
  function clearSelection() {
    canvasState.value.selectedNodes = []
    canvasState.value.selectedEdges = []
  }
  
  /**
   * 更新视口
   */
  function updateViewport(viewport: { x: number; y: number; zoom: number }) {
    canvasState.value.viewport = viewport
  }
  
  /**
   * 验证工作流
   */
  function validateWorkflow(): ValidationResult {
    const errors: any[] = []
    const warnings: any[] = []
    
    // 检查是否有节点
    if (canvasState.value.nodes.length === 0) {
      errors.push({
        type: 'error',
        message: '工作流必须包含至少一个节点',
        severity: 'critical',
      })
    }
    
    // 检查是否有孤立节点
    const connectedNodes = new Set<string>()
    canvasState.value.edges.forEach(edge => {
      connectedNodes.add(edge.source)
      connectedNodes.add(edge.target)
    })
    
    canvasState.value.nodes.forEach(node => {
      if (!connectedNodes.has(node.id) && canvasState.value.nodes.length > 1) {
        warnings.push({
          type: 'warning',
          nodeId: node.id,
          message: `节点 "${node.label}" 未连接到其他节点`,
          severity: 'minor',
        })
      }
    })
    
    // 检查是否有循环
    // TODO: 实现更复杂的 DAG 验证
    
    return {
      valid: errors.length === 0,
      errors,
      warnings,
    }
  }
  
  /**
   * 执行工作流
   */
  async function executeWorkflow(workflowId: string, inputs: Record<string, any>) {
    loading.value = true
    error.value = null
    
    try {
      const { executeWorkflow } = await import('../api/workflows')
      const execution = await executeWorkflow(workflowId, inputs)
      executions.value.unshift(execution)
      currentExecution.value = execution
      return execution
    } catch (err) {
      error.value = '执行工作流失败'
      throw err
    } finally {
      loading.value = false
    }
  }
  
  /**
   * 取消执行
   */
  async function cancelExecution(executionId: string) {
    try {
      const { cancelExecution } = await import('../api/workflows')
      await cancelExecution(executionId)
      
      // 更新状态
      const execution = executions.value.find(e => e.id === executionId)
      if (execution) {
        execution.status = 'cancelled'
      }
      
      if (currentExecution.value?.id === executionId) {
        currentExecution.value.status = 'cancelled'
      }
    } catch (err) {
      console.error('Failed to cancel execution:', err)
    }
  }
  
  /**
   * 加载执行历史
   */
  async function loadExecutions(workflowId?: string) {
    try {
      const { getExecutions } = await import('../api/workflows')
      const data = await getExecutions(workflowId)
      executions.value = data
      return data
    } catch (err) {
      console.error('Failed to load executions:', err)
    }
  }
  
  /**
   * 加载团队 Agent
   */
  async function loadAgents(flowId?: string) {
    try {
      const { getAgents } = await import('../api/agents')
      const data = await getAgents(flowId)
      agents.value = data
      return data
    } catch (err) {
      console.error('Failed to load agents:', err)
    }
  }
  
  /**
   * 创建 Agent
   */
  async function createAgent(data: {
    name: string
    role: string
    config?: Record<string, any>
    flowId?: string
  }) {
    try {
      const { createAgent } = await import('../api/agents')
      const agent = await createAgent(data)
      agents.value.push(agent)
      return agent
    } catch (err) {
      console.error('Failed to create agent:', err)
      throw err
    }
  }
  
  /**
   * 归档 Agent
   */
  async function archiveAgent(agentId: string) {
    try {
      const { archiveAgent } = await import('../api/agents')
      await archiveAgent(agentId)
      
      const agent = agents.value.find(a => a.id === agentId)
      if (agent) {
        agent.status = 'archived'
      }
    } catch (err) {
      console.error('Failed to archive agent:', err)
    }
  }
  
  /**
   * 加载模板
   */
  async function loadTemplates(category?: string) {
    try {
      const { getTemplates } = await import('../api/templates')
      const data = await getTemplates(category)
      templates.value = data
      return data
    } catch (err) {
      console.error('Failed to load templates:', err)
    }
  }
  
  /**
   * 从模板创建工作流
   */
  async function createFromTemplate(templateId: string, data?: {
    name?: string
    description?: string
  }) {
    loading.value = true
    error.value = null
    
    try {
      const { instantiateTemplate } = await import('../api/templates')
      const workflow = await instantiateTemplate(templateId, data)
      workflows.value.unshift(workflow)
      currentWorkflow.value = workflow
      return workflow
    } catch (err) {
      error.value = '从模板创建工作流失败'
      throw err
    } finally {
      loading.value = false
    }
  }
  
  /**
   * 重置状态
   */
  function $reset() {
    currentWorkflow.value = null
    workflows.value = []
    executions.value = []
    currentExecution.value = null
    agents.value = []
    templates.value = []
    canvasState.value = {
      nodes: [],
      edges: [],
      viewport: { x: 0, y: 0, zoom: 1 },
      selectedNodes: [],
      selectedEdges: [],
    }
    loading.value = false
    error.value = null
    nodesLoaded.value = false
  }
  
  // ==================== 返回 ====================
  
  return {
    // 状态
    currentWorkflow,
    workflows,
    executions,
    currentExecution,
    agents,
    templates,
    canvasState,
    loading,
    error,
    nodesLoaded,
    
    // 计算属性
    currentNodes,
    currentEdges,
    hasSelection,
    selectedNodes,
    selectedEdges,
    activeExecutions,
    activeAgents,
    
    // 操作
    loadNodeDefinitions,
    loadWorkflows,
    loadWorkflow,
    createWorkflow,
    updateWorkflow,
    deleteWorkflow,
    saveCanvasState,
    updateNodes,
    updateEdges,
    addNode,
    removeNode,
    addEdge,
    removeEdge,
    selectNode,
    selectEdge,
    clearSelection,
    updateViewport,
    validateWorkflow,
    executeWorkflow,
    cancelExecution,
    loadExecutions,
    loadAgents,
    createAgent,
    archiveAgent,
    loadTemplates,
    createFromTemplate,
    $reset,
  }
})

// ==================== 画布 Store ====================

export const useCanvasStore = defineStore('canvas', () => {
  // 历史记录
  const history = ref<{
    past: Array<{ nodes: WorkflowNode[]; edges: WorkflowEdge[] }>
    future: Array<{ nodes: WorkflowNode[]; edges: WorkflowEdge[] }>
  }>({
    past: [],
    future: [],
  })
  
  // 剪贴板
  const clipboard = ref<{
    nodes: WorkflowNode[]
    edges: WorkflowEdge[]
  } | null>(null)
  
  // 配置
  const config = ref({
    showGrid: true,
    showMinimap: false,
    snapToGrid: true,
    gridSize: 20,
    enableAnimations: true,
  })
  
  // ==================== 计算属性 ====================
  
  const canUndo = computed(() => history.value.past.length > 0)
  const canRedo = computed(() => history.value.future.length > 0)
  const canPaste = computed(() => clipboard.value !== null)
  
  // ==================== 操作 ====================
  
  /**
   * 保存到历史
   */
  function saveToHistory(nodes: WorkflowNode[], edges: WorkflowEdge[]) {
    history.value.past.push({ nodes: [...nodes], edges: [...edges] })
    history.value.future = []
    
    // 限制历史记录大小
    if (history.value.past.length > 50) {
      history.value.past.shift()
    }
  }
  
  /**
   * 撤销
   */
  function undo(currentNodes: WorkflowNode[], currentEdges: WorkflowEdge[]): {
    nodes: WorkflowNode[]
    edges: WorkflowEdge[]
  } | null {
    if (!canUndo.value) return null
    
    const previous = history.value.past.pop()!
    history.value.future.push({ nodes: [...currentNodes], edges: [...currentEdges] })
    
    return previous
  }
  
  /**
   * 重做
   */
  function redo(currentNodes: WorkflowNode[], currentEdges: WorkflowEdge[]): {
    nodes: WorkflowNode[]
    edges: WorkflowEdge[]
  } | null {
    if (!canRedo.value) return null
    
    const next = history.value.future.pop()!
    history.value.past.push({ nodes: [...currentNodes], edges: [...currentEdges] })
    
    return next
  }
  
  /**
   * 复制
   */
  function copy(nodes: WorkflowNode[], edges: WorkflowEdge[]) {
    clipboard.value = { nodes: [...nodes], edges: [...edges] }
  }
  
  /**
   * 粘贴
   */
  function paste(currentNodes: WorkflowNode[], currentEdges: WorkflowEdge[]): {
    nodes: WorkflowNode[]
    edges: WorkflowEdge[]
  } | null {
    if (!clipboard.value) return null
    
    const offset = { x: 50, y: 50 }
    const nodeMap = new Map<string, string>()
    
    // 粘贴节点
    const newNodes = clipboard.value.nodes.map(node => {
      const newId = `${node.id}_copy_${Date.now()}`
      nodeMap.set(node.id, newId)
      
      return {
        ...node,
        id: newId,
        position: {
          x: node.position.x + offset.x,
          y: node.position.y + offset.y,
        },
      }
    })
    
    // 粘贴边
    const newEdges = clipboard.value.edges.map(edge => ({
      ...edge,
      id: `${edge.id}_copy_${Date.now()}`,
      source: nodeMap.get(edge.source) || edge.source,
      target: nodeMap.get(edge.target) || edge.target,
    }))
    
    return {
      nodes: [...currentNodes, ...newNodes],
      edges: [...currentEdges, ...newEdges],
    }
  }
  
  /**
   * 清除历史
   */
  function clearHistory() {
    history.value = { past: [], future: [] }
  }
  
  /**
   * 清除剪贴板
   */
  function clearClipboard() {
    clipboard.value = null
  }
  
  /**
   * 更新配置
   */
  function updateConfig(newConfig: Partial<typeof config.value>) {
    config.value = { ...config.value, ...newConfig }
  }
  
  /**
   * 重置
   */
  function $reset() {
    history.value = { past: [], future: [] }
    clipboard.value = null
    config.value = {
      showGrid: true,
      showMinimap: false,
      snapToGrid: true,
      gridSize: 20,
      enableAnimations: true,
    }
  }
  
  return {
    // 状态
    history,
    clipboard,
    config,
    
    // 计算属性
    canUndo,
    canRedo,
    canPaste,
    
    // 操作
    saveToHistory,
    undo,
    redo,
    copy,
    paste,
    clearHistory,
    clearClipboard,
    updateConfig,
    $reset,
  }
})