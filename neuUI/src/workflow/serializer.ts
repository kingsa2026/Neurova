/**
 * 工作流序列化器
 * 处理工作流定义的序列化和反序列化
 */

import type {
  WorkflowDefinition,
  WorkflowNode,
  WorkflowEdge,
  WorkflowVariable,
  SerializedWorkflow,
} from './types'

// 导出格式
export type ExportFormat = 'json' | 'yaml' | 'svg' | 'png'

// 序列化选项
export interface SerializationOptions {
  includeMetadata?: boolean
  includePositions?: boolean
  includeStyles?: boolean
  prettyPrint?: boolean
  indent?: number
}

// 默认序列化选项
const defaultOptions: SerializationOptions = {
  includeMetadata: true,
  includePositions: true,
  includeStyles: true,
  prettyPrint: true,
  indent: 2,
}

/**
 * 序列化工作流
 */
export function serializeWorkflow(
  workflow: WorkflowDefinition,
  options: SerializationOptions = {}
): SerializedWorkflow {
  const opts = { ...defaultOptions, ...options }

  const serialized: SerializedWorkflow = {
    version: '1.0.0',
    format: 'neurflow',
    timestamp: Date.now(),
    workflow: {
      id: workflow.id,
      name: workflow.name,
      description: workflow.description,
      category: workflow.category,
      status: workflow.status,
      version: workflow.version,
      tags: workflow.tags,
      nodes: workflow.nodes.map(node => serializeNode(node, opts)),
      edges: workflow.edges.map(edge => serializeEdge(edge, opts)),
      variables: workflow.variables,
    },
  }

  if (opts.includeMetadata) {
    serialized.metadata = {
      author: workflow.createdBy,
      createdAt: workflow.createdAt,
      updatedAt: workflow.updatedAt,
      nodeCount: workflow.nodes.length,
      edgeCount: workflow.edges.length,
    }
  }

  return serialized
}

/**
 * 序列化节点
 */
function serializeNode(node: WorkflowNode, options: SerializationOptions): any {
  const serialized: any = {
    id: node.id,
    type: node.type,
    label: node.label,
    data: node.data || {},
  }

  if (options.includePositions && node.position) {
    serialized.position = node.position
  }

  if (options.includeStyles && node.style) {
    serialized.style = node.style
  }

  if (node.inputs && node.inputs.length > 0) {
    serialized.inputs = node.inputs
  }

  if (node.outputs && node.outputs.length > 0) {
    serialized.outputs = node.outputs
  }

  return serialized
}

/**
 * 序列化边
 */
function serializeEdge(edge: WorkflowEdge, options: SerializationOptions): any {
  const serialized: any = {
    id: edge.id,
    source: edge.source,
    target: edge.target,
    sourceHandle: edge.sourceHandle,
    targetHandle: edge.targetHandle,
  }

  if (options.includeStyles && edge.style) {
    serialized.style = edge.style
  }

  if (edge.label) {
    serialized.label = edge.label
  }

  if (edge.animated !== undefined) {
    serialized.animated = edge.animated
  }

  return serialized
}

/**
 * 反序列化工作流
 */
export function deserializeWorkflow(data: SerializedWorkflow): WorkflowDefinition {
  if (data.format !== 'neurflow') {
    throw new Error(`不支持的格式: ${data.format}`)
  }

  const workflow = data.workflow

  return {
    id: workflow.id || generateId(),
    name: workflow.name,
    description: workflow.description,
    category: workflow.category,
    status: workflow.status || 'draft',
    version: workflow.version || '1.0.0',
    tags: workflow.tags || [],
    nodes: workflow.nodes.map(node => deserializeNode(node)),
    edges: workflow.edges.map(edge => deserializeEdge(edge)),
    variables: workflow.variables || [],
    createdAt: data.metadata?.createdAt || Date.now(),
    updatedAt: data.metadata?.updatedAt || Date.now(),
    createdBy: data.metadata?.author,
  }
}

/**
 * 反序列化节点
 */
function deserializeNode(data: any): WorkflowNode {
  return {
    id: data.id || generateId(),
    type: data.type,
    label: data.label,
    position: data.position || { x: 0, y: 0 },
    data: data.data || {},
    style: data.style,
    inputs: data.inputs || [],
    outputs: data.outputs || [],
  }
}

/**
 * 反序列化边
 */
function deserializeEdge(data: any): WorkflowEdge {
  return {
    id: data.id || generateId(),
    source: data.source,
    target: data.target,
    sourceHandle: data.sourceHandle,
    targetHandle: data.targetHandle,
    style: data.style,
    label: data.label,
    animated: data.animated,
  }
}

/**
 * 导出工作流
 */
export function exportWorkflow(
  workflow: WorkflowDefinition,
  format: ExportFormat,
  options: SerializationOptions = {}
): string {
  switch (format) {
    case 'json':
      return exportAsJSON(workflow, options)
    case 'yaml':
      return exportAsYAML(workflow, options)
    case 'svg':
      return exportAsSVG(workflow)
    case 'png':
      throw new Error('PNG 导出需要使用 canvas API')
    default:
      throw new Error(`不支持的导出格式: ${format}`)
  }
}

/**
 * 导出为 JSON
 */
function exportAsJSON(workflow: WorkflowDefinition, options: SerializationOptions): string {
  const serialized = serializeWorkflow(workflow, options)
  if (options.prettyPrint) {
    return JSON.stringify(serialized, null, options.indent)
  }
  return JSON.stringify(serialized)
}

/**
 * 导出为 YAML
 */
function exportAsYAML(workflow: WorkflowDefinition, options: SerializationOptions): string {
  const serialized = serializeWorkflow(workflow, options)
  return convertToYAML(serialized, 0)
}

/**
 * 简单的 YAML 转换器
 */
function convertToYAML(obj: any, indent: number): string {
  const spaces = '  '.repeat(indent)
  let yaml = ''

  if (Array.isArray(obj)) {
    for (const item of obj) {
      if (typeof item === 'object' && item !== null) {
        yaml += `${spaces}-\n${convertToYAML(item, indent + 1)}`
      } else {
        yaml += `${spaces}- ${formatYAMLValue(item)}\n`
      }
    }
  } else if (typeof obj === 'object' && obj !== null) {
    for (const [key, value] of Object.entries(obj)) {
      if (typeof value === 'object' && value !== null) {
        yaml += `${spaces}${key}:\n${convertToYAML(value, indent + 1)}`
      } else {
        yaml += `${spaces}${key}: ${formatYAMLValue(value)}\n`
      }
    }
  } else {
    yaml += `${spaces}${formatYAMLValue(obj)}\n`
  }

  return yaml
}

/**
 * 格式化 YAML 值
 */
function formatYAMLValue(value: any): string {
  if (value === null || value === undefined) {
    return 'null'
  }
  if (typeof value === 'string') {
    if (value.includes('\n') || value.includes(':') || value.includes('#')) {
      return `"${value.replace(/"/g, '\\"')}"`
    }
    return value
  }
  if (typeof value === 'boolean') {
    return value ? 'true' : 'false'
  }
  if (typeof value === 'number') {
    return String(value)
  }
  return String(value)
}

/**
 * 导出为 SVG
 */
function exportAsSVG(workflow: WorkflowDefinition): string {
  const nodes = workflow.nodes
  const edges = workflow.edges

  // 计算画布大小
  let maxX = 0
  let maxY = 0
  for (const node of nodes) {
    maxX = Math.max(maxX, (node.position?.x || 0) + 200)
    maxY = Math.max(maxY, (node.position?.y || 0) + 100)
  }

  const width = maxX + 100
  const height = maxY + 100

  let svg = `<?xml version="1.0" encoding="UTF-8"?>
<svg width="${width}" height="${height}" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <style>
      .node { fill: white; stroke: #1890ff; stroke-width: 2; }
      .node-header { fill: #1890ff; }
      .node-text { fill: white; font-size: 12px; font-family: sans-serif; }
      .edge { stroke: #666; stroke-width: 2; fill: none; }
      .edge-label { fill: #666; font-size: 10px; font-family: sans-serif; }
    </style>
    <marker id="arrowhead" markerWidth="10" markerHeight="7" refX="10" refY="3.5" orient="auto">
      <polygon points="0 0, 10 3.5, 0 7" fill="#666" />
    </marker>
  </defs>
  <rect width="100%" height="100%" fill="#f5f5f5" />
`

  // 绘制边
  for (const edge of edges) {
    const sourceNode = nodes.find(n => n.id === edge.source)
    const targetNode = nodes.find(n => n.id === edge.target)
    
    if (sourceNode && targetNode) {
      const x1 = (sourceNode.position?.x || 0) + 100
      const y1 = (sourceNode.position?.y || 0) + 50
      const x2 = (targetNode.position?.x || 0)
      const y2 = (targetNode.position?.y || 0) + 50
      
      const midX = (x1 + x2) / 2
      
      svg += `  <path d="M ${x1} ${y1} C ${midX} ${y1}, ${midX} ${y2}, ${x2} ${y2}" class="edge" marker-end="url(#arrowhead)" />\n`
      
      if (edge.label) {
        svg += `  <text x="${midX}" y="${(y1 + y2) / 2 - 10}" class="edge-label" text-anchor="middle">${edge.label}</text>\n`
      }
    }
  }

  // 绘制节点
  for (const node of nodes) {
    const x = node.position?.x || 0
    const y = node.position?.y || 0
    
    svg += `  <g transform="translate(${x}, ${y})">\n`
    svg += `    <rect class="node" width="200" height="80" rx="8" />\n`
    svg += `    <rect class="node-header" width="200" height="30" rx="8" />\n`
    svg += `    <rect class="node-header" width="200" height="30" y="0" />\n`
    svg += `    <text class="node-text" x="100" y="20" text-anchor="middle">${escapeXML(node.label || node.type)}</text>\n`
    svg += `    <text x="100" y="55" text-anchor="middle" fill="#666" font-size="10">${escapeXML(node.type)}</text>\n`
    svg += `  </g>\n`
  }

  svg += '</svg>'
  return svg
}

/**
 * 转义 XML 特殊字符
 */
function escapeXML(str: string): string {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&apos;')
}

/**
 * 导入工作流
 */
export function importWorkflow(data: string, format?: ExportFormat): WorkflowDefinition {
  // 自动检测格式
  if (!format) {
    format = detectFormat(data)
  }

  switch (format) {
    case 'json':
      return importFromJSON(data)
    case 'yaml':
      throw new Error('YAML 导入暂不支持')
    default:
      throw new Error(`不支持的导入格式: ${format}`)
  }
}

/**
 * 检测数据格式
 */
function detectFormat(data: string): ExportFormat {
  const trimmed = data.trim()
  
  if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
    return 'json'
  }
  if (trimmed.startsWith('<?xml') || trimmed.startsWith('<svg')) {
    return 'svg'
  }
  if (trimmed.includes(':') && !trimmed.includes('{')) {
    return 'yaml'
  }
  
  return 'json'
}

/**
 * 从 JSON 导入
 */
function importFromJSON(data: string): WorkflowDefinition {
  try {
    const parsed = JSON.parse(data)
    
    // 检查是否是序列化格式
    if (parsed.format === 'neurflow') {
      return deserializeWorkflow(parsed)
    }
    
    // 否则尝试直接转换
    return {
      id: parsed.id || generateId(),
      name: parsed.name || '导入的工作流',
      description: parsed.description,
      category: parsed.category,
      status: parsed.status || 'draft',
      version: parsed.version || '1.0.0',
      tags: parsed.tags || [],
      nodes: parsed.nodes || [],
      edges: parsed.edges || [],
      variables: parsed.variables || [],
      createdAt: parsed.createdAt || Date.now(),
      updatedAt: parsed.updatedAt || Date.now(),
      createdBy: parsed.createdBy,
    }
  } catch (error) {
    throw new Error(`JSON 解析失败: ${error}`)
  }
}

/**
 * 生成唯一 ID
 */
function generateId(): string {
  return `wf_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`
}

/**
 * 克隆工作流
 */
export function cloneWorkflow(workflow: WorkflowDefinition): WorkflowDefinition {
  const serialized = serializeWorkflow(workflow)
  const cloned = deserializeWorkflow(serialized)
  cloned.id = generateId()
  cloned.name = `${workflow.name} (副本)`
  cloned.status = 'draft'
  cloned.createdAt = Date.now()
  cloned.updatedAt = Date.now()
  return cloned
}

/**
 * 合并工作流
 */
export function mergeWorkflows(
  base: WorkflowDefinition,
  overlay: Partial<WorkflowDefinition>
): WorkflowDefinition {
  return {
    ...base,
    ...overlay,
    id: base.id,
    nodes: overlay.nodes || base.nodes,
    edges: overlay.edges || base.edges,
    variables: overlay.variables || base.variables,
    updatedAt: Date.now(),
  }
}