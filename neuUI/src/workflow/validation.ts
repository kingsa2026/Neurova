/**
 * 工作流验证器
 * 验证工作流定义的正确性和完整性
 */

import type {
  WorkflowDefinition,
  WorkflowNode,
  WorkflowEdge,
  ValidationResult,
  ValidationError,
  NodePort,
} from './types'

// 验证选项
export interface ValidationOptions {
  checkConnections?: boolean
  checkCycles?: boolean
  checkRequiredFields?: boolean
  checkTypeCompatibility?: boolean
  strict?: boolean
}

// 默认验证选项
const defaultOptions: ValidationOptions = {
  checkConnections: true,
  checkCycles: true,
  checkRequiredFields: true,
  checkTypeCompatibility: true,
  strict: false,
}

/**
 * 验证工作流定义
 */
export function validateWorkflow(
  workflow: WorkflowDefinition,
  options: ValidationOptions = {}
): ValidationResult {
  const opts = { ...defaultOptions, ...options }
  const errors: ValidationError[] = []
  const warnings: ValidationError[] = []

  // 1. 基本验证
  validateBasicStructure(workflow, errors, warnings)

  // 2. 节点验证
  validateNodes(workflow.nodes, errors, warnings, opts)

  // 3. 连接验证
  if (opts.checkConnections) {
    validateConnections(workflow.nodes, workflow.edges, errors, warnings, opts)
  }

  // 4. 循环检测
  if (opts.checkCycles) {
    validateCycles(workflow.nodes, workflow.edges, errors, warnings)
  }

  return {
    valid: errors.length === 0,
    errors,
    warnings,
  }
}

/**
 * 验证基本结构
 */
function validateBasicStructure(
  workflow: WorkflowDefinition,
  errors: ValidationError[],
  warnings: ValidationError[]
) {
  if (!workflow.name || workflow.name.trim() === '') {
    errors.push({
      type: 'error',
      message: '工作流名称不能为空',
      field: 'name',
    })
  }

  if (!workflow.nodes || workflow.nodes.length === 0) {
    errors.push({
      type: 'error',
      message: '工作流至少需要一个节点',
      field: 'nodes',
    })
  }

  if (workflow.nodes && workflow.nodes.length > 100) {
    warnings.push({
      type: 'warning',
      message: '工作流节点数量过多，可能影响性能',
      field: 'nodes',
      suggestion: '考虑将复杂工作流拆分为多个子工作流',
    })
  }
}

/**
 * 验证节点
 */
function validateNodes(
  nodes: WorkflowNode[],
  errors: ValidationError[],
  warnings: ValidationError[],
  options: ValidationOptions
) {
  const nodeIds = new Set<string>()

  for (const node of nodes) {
    // 检查节点 ID 唯一性
    if (nodeIds.has(node.id)) {
      errors.push({
        type: 'error',
        message: `节点 ID "${node.id}" 重复`,
        nodeId: node.id,
        field: 'id',
      })
    }
    nodeIds.add(node.id)

    // 检查节点类型
    if (!node.type || node.type.trim() === '') {
      errors.push({
        type: 'error',
        message: `节点 "${node.id}" 缺少类型`,
        nodeId: node.id,
        field: 'type',
      })
    }

    // 检查节点位置
    if (node.position && (isNaN(node.position.x) || isNaN(node.position.y))) {
      errors.push({
        type: 'error',
        message: `节点 "${node.id}" 位置无效`,
        nodeId: node.id,
        field: 'position',
      })
    }

    // 检查必需字段
    if (options.checkRequiredFields) {
      validateNodeRequiredFields(node, errors, warnings)
    }
  }
}

/**
 * 验证节点必需字段
 */
function validateNodeRequiredFields(
  node: WorkflowNode,
  errors: ValidationError[],
  warnings: ValidationError[]
) {
  const data = node.data || {}

  switch (node.type) {
    case 'builtin:llm':
      if (!data.prompt && !data.model) {
        warnings.push({
          type: 'warning',
          message: `LLM 节点 "${node.id}" 未配置提示词或模型`,
          nodeId: node.id,
          suggestion: '配置提示词或选择模型以使用默认提示',
        })
      }
      break

    case 'builtin:condition':
      if (!data.expression) {
        errors.push({
          type: 'error',
          message: `条件节点 "${node.id}" 缺少条件表达式`,
          nodeId: node.id,
          field: 'expression',
        })
      }
      break

    case 'builtin:code':
      if (!data.code) {
        errors.push({
          type: 'error',
          message: `代码节点 "${node.id}" 缺少代码`,
          nodeId: node.id,
          field: 'code',
        })
      }
      break

    case 'builtin:http':
      if (!data.url) {
        errors.push({
          type: 'error',
          message: `HTTP 节点 "${node.id}" 缺少 URL`,
          nodeId: node.id,
          field: 'url',
        })
      }
      break

    case 'builtin:memory_search':
      if (!data.query) {
        warnings.push({
          type: 'warning',
          message: `记忆搜索节点 "${node.id}" 未配置查询`,
          nodeId: node.id,
          suggestion: '配置查询变量以搜索相关记忆',
        })
      }
      break

    case 'builtin:memory_save':
      if (!data.content) {
        errors.push({
          type: 'error',
          message: `记忆保存节点 "${node.id}" 缺少保存内容`,
          nodeId: node.id,
          field: 'content',
        })
      }
      break
  }
}

/**
 * 验证连接
 */
function validateConnections(
  nodes: WorkflowNode[],
  edges: WorkflowEdge[],
  errors: ValidationError[],
  warnings: ValidationError[],
  options: ValidationOptions
) {
  const nodeMap = new Map<string, WorkflowNode>()
  for (const node of nodes) {
    nodeMap.set(node.id, node)
  }

  for (const edge of edges) {
    // 检查源节点存在
    if (!nodeMap.has(edge.source)) {
      errors.push({
        type: 'error',
        message: `边 "${edge.id}" 的源节点 "${edge.source}" 不存在`,
        edgeId: edge.id,
        field: 'source',
      })
    }

    // 检查目标节点存在
    if (!nodeMap.has(edge.target)) {
      errors.push({
        type: 'error',
        message: `边 "${edge.id}" 的目标节点 "${edge.target}" 不存在`,
        edgeId: edge.id,
        field: 'target',
      })
    }

    // 检查端口存在
    const sourceNode = nodeMap.get(edge.source)
    const targetNode = nodeMap.get(edge.target)

    if (sourceNode && edge.sourceHandle) {
      const portExists = sourceNode.outputs?.some(p => p.id === edge.sourceHandle)
      if (!portExists) {
        errors.push({
          type: 'error',
          message: `边 "${edge.id}" 的源端口 "${edge.sourceHandle}" 不存在`,
          edgeId: edge.id,
          field: 'sourceHandle',
        })
      }
    }

    if (targetNode && edge.targetHandle) {
      const portExists = targetNode.inputs?.some(p => p.id === edge.targetHandle)
      if (!portExists) {
        errors.push({
          type: 'error',
          message: `边 "${edge.id}" 的目标端口 "${edge.targetHandle}" 不存在`,
          edgeId: edge.id,
          field: 'targetHandle',
        })
      }
    }

    // 检查类型兼容性
    if (options.checkTypeCompatibility && sourceNode && targetNode) {
      validateTypeCompatibility(edge, sourceNode, targetNode, errors, warnings)
    }
  }

  // 检查输入节点必须有输入
  for (const node of nodes) {
    if (node.type === 'builtin:input') {
      const hasIncoming = edges.some(e => e.target === node.id)
      if (hasIncoming) {
        warnings.push({
          type: 'warning',
          message: `输入节点 "${node.id}" 不应该有输入连接`,
          nodeId: node.id,
          suggestion: '输入节点是工作流的起点，只能有输出连接',
        })
      }
    }
  }

  // 检查输出节点必须有输出
  for (const node of nodes) {
    if (node.type === 'builtin:output') {
      const hasOutgoing = edges.some(e => e.source === node.id)
      if (hasOutgoing) {
        warnings.push({
          type: 'warning',
          message: `输出节点 "${node.id}" 不应该有输出连接`,
          nodeId: node.id,
          suggestion: '输出节点是工作流的终点，只能有输入连接',
        })
      }
    }
  }
}

/**
 * 验证类型兼容性
 */
function validateTypeCompatibility(
  edge: WorkflowEdge,
  sourceNode: WorkflowNode,
  targetNode: WorkflowNode,
  errors: ValidationError[],
  warnings: ValidationError[]
) {
  if (!edge.sourceHandle || !edge.targetHandle) return

  const sourcePort = sourceNode.outputs?.find(p => p.id === edge.sourceHandle)
  const targetPort = targetNode.inputs?.find(p => p.id === edge.targetHandle)

  if (!sourcePort || !targetPort) return

  // 检查类型兼容性
  if (!areTypesCompatible(sourcePort.type, targetPort.type)) {
    warnings.push({
      type: 'warning',
      message: `边 "${edge.id}" 的类型不兼容: ${sourcePort.type} -> ${targetPort.type}`,
      edgeId: edge.id,
      suggestion: '添加类型转换节点或使用 any 类型',
    })
  }
}

/**
 * 检查类型是否兼容
 */
function areTypesCompatible(sourceType: string, targetType: string): boolean {
  // any 类型兼容所有类型
  if (sourceType === 'any' || targetType === 'any') return true

  // 相同类型兼容
  if (sourceType === targetType) return true

  // 数字可以转换为字符串
  if (sourceType === 'number' && targetType === 'string') return true

  // 布尔可以转换为字符串
  if (sourceType === 'boolean' && targetType === 'string') return true

  return false
}

/**
 * 验证循环
 */
function validateCycles(
  nodes: WorkflowNode[],
  edges: WorkflowEdge[],
  errors: ValidationError[],
  warnings: ValidationError[]
) {
  // 构建邻接表
  const adjacencyList = new Map<string, string[]>()
  for (const node of nodes) {
    adjacencyList.set(node.id, [])
  }
  for (const edge of edges) {
    const neighbors = adjacencyList.get(edge.source) || []
    neighbors.push(edge.target)
    adjacencyList.set(edge.source, neighbors)
  }

  // 使用 DFS 检测循环
  const visited = new Set<string>()
  const recursionStack = new Set<string>()
  const cycles: string[][] = []

  function dfs(nodeId: string, path: string[]): boolean {
    visited.add(nodeId)
    recursionStack.add(nodeId)
    path.push(nodeId)

    const neighbors = adjacencyList.get(nodeId) || []
    for (const neighbor of neighbors) {
      if (!visited.has(neighbor)) {
        if (dfs(neighbor, [...path])) {
          return true
        }
      } else if (recursionStack.has(neighbor)) {
        // 找到循环
        const cycleStart = path.indexOf(neighbor)
        const cycle = path.slice(cycleStart)
        cycles.push(cycle)
        return true
      }
    }

    recursionStack.delete(nodeId)
    return false
  }

  // 对每个未访问的节点进行 DFS
  for (const node of nodes) {
    if (!visited.has(node.id)) {
      dfs(node.id, [])
    }
  }

  // 报告循环
  if (cycles.length > 0) {
    for (const cycle of cycles) {
      // 检查是否包含循环节点（允许循环）
      const hasLoopNode = cycle.some(nodeId => {
        const node = nodes.find(n => n.id === nodeId)
        return node?.type === 'builtin:loop'
      })

      if (!hasLoopNode) {
        errors.push({
          type: 'error',
          message: `检测到循环: ${cycle.join(' -> ')}`,
          field: 'edges',
        })
      } else {
        warnings.push({
          type: 'warning',
          message: `检测到循环（包含循环节点）: ${cycle.join(' -> ')}`,
          field: 'edges',
          suggestion: '确保循环有明确的退出条件',
        })
      }
    }
  }
}

/**
 * 快速验证（只检查关键错误）
 */
export function validateWorkflowQuick(workflow: WorkflowDefinition): ValidationResult {
  return validateWorkflow(workflow, {
    checkConnections: false,
    checkCycles: false,
    checkRequiredFields: false,
    checkTypeCompatibility: false,
  })
}

/**
 * 验证单个节点
 */
export function validateNode(
  node: WorkflowNode,
  options: ValidationOptions = {}
): ValidationResult {
  const errors: ValidationError[] = []
  const warnings: ValidationError[] = []

  validateNodeRequiredFields(node, errors, warnings)

  return {
    valid: errors.length === 0,
    errors,
    warnings,
  }
}

/**
 * 验证单个连接
 */
export function validateEdge(
  edge: WorkflowEdge,
  sourceNode: WorkflowNode,
  targetNode: WorkflowNode,
  options: ValidationOptions = {}
): ValidationResult {
  const errors: ValidationError[] = []
  const warnings: ValidationError[] = []

  // 检查端口存在
  if (edge.sourceHandle) {
    const portExists = sourceNode.outputs?.some(p => p.id === edge.sourceHandle)
    if (!portExists) {
      errors.push({
        type: 'error',
        message: `源端口 "${edge.sourceHandle}" 不存在`,
        edgeId: edge.id,
        field: 'sourceHandle',
      })
    }
  }

  if (edge.targetHandle) {
    const portExists = targetNode.inputs?.some(p => p.id === edge.targetHandle)
    if (!portExists) {
      errors.push({
        type: 'error',
        message: `目标端口 "${edge.targetHandle}" 不存在`,
        edgeId: edge.id,
        field: 'targetHandle',
      })
    }
  }

  // 检查类型兼容性
  if (options.checkTypeCompatibility) {
    validateTypeCompatibility(edge, sourceNode, targetNode, errors, warnings)
  }

  return {
    valid: errors.length === 0,
    errors,
    warnings,
  }
}