/**
 * 工具/技能/MCP 适配器
 * 将外部能力转换为节点定义
 */

import type { SubBlockConfig, NodeDefinition, NodePort } from '../types'

// 工具定义接口
export interface ToolDefinition {
  name: string
  description: string
  parameters: Record<string, any>
  returns?: any
  category?: string
  tags?: string[]
}

// 技能定义接口
export interface SkillDefinition {
  name: string
  description: string
  version?: string
  author?: string
  inputs?: Array<{
    name: string
    type: string
    required?: boolean
    description?: string
  }>
  outputs?: Array<{
    name: string
    type: string
    description?: string
  }>
  category?: string
  tags?: string[]
}

// MCP 工具定义接口
export interface MCPToolDefinition {
  server: string
  tool: string
  description: string
  inputSchema: Record<string, any>
  category?: string
  tags?: string[]
}

// ==================== 工具适配器 ====================

/**
 * 将工具定义转换为节点定义
 */
export function adaptToolToNode(tool: ToolDefinition): NodeDefinition {
  const subBlocks: SubBlockConfig[] = []
  const inputs: NodePort[] = []
  const outputs: NodePort[] = []

  // 解析参数
  if (tool.parameters) {
    const properties = tool.parameters.properties || tool.parameters
    const required = tool.parameters.required || []

    for (const [name, schema] of Object.entries(properties as Record<string, any>)) {
      const paramSchema = schema as any
      
      // 创建 SubBlock
      subBlocks.push({
        id: name,
        title: paramSchema.title || name,
        type: mapJsonSchemaToSubBlockType(paramSchema),
        description: paramSchema.description,
        required: required.includes(name),
        defaultValue: paramSchema.default,
        options: paramSchema.enum?.map((val: any) => ({
          label: String(val),
          value: val,
        })),
        min: paramSchema.minimum,
        max: paramSchema.maximum,
      })

      // 创建输入端口
      inputs.push({
        id: name,
        name: name,
        type: mapJsonSchemaTypeToPortType(paramSchema.type),
        required: required.includes(name),
        description: paramSchema.description,
      })
    }
  }

  // 默认输出端口
  outputs.push({
    id: 'output',
    name: '输出',
    type: 'any',
    description: '工具执行结果',
  })

  return {
    type: `tool:${tool.name}`,
    label: tool.name,
    icon: 'ToolOutlined',
    category: tool.category || 'tools',
    description: tool.description,
    subBlocks,
    inputs,
    outputs,
    source: 'tool',
    tags: tool.tags || [],
  }
}

// ==================== 技能适配器 ====================

/**
 * 将技能定义转换为节点定义
 */
export function adaptSkillToNode(skill: SkillDefinition): NodeDefinition {
  const subBlocks: SubBlockConfig[] = []
  const inputs: NodePort[] = []
  const outputs: NodePort[] = []

  // 解析输入
  if (skill.inputs) {
    for (const input of skill.inputs) {
      subBlocks.push({
        id: input.name,
        title: input.name,
        type: mapTypeToSubBlockType(input.type),
        description: input.description,
        required: input.required,
      })

      inputs.push({
        id: input.name,
        name: input.name,
        type: mapTypeToPortType(input.type),
        required: input.required,
        description: input.description,
      })
    }
  }

  // 解析输出
  if (skill.outputs) {
    for (const output of skill.outputs) {
      outputs.push({
        id: output.name,
        name: output.name,
        type: mapTypeToPortType(output.type),
        description: output.description,
      })
    }
  } else {
    // 默认输出
    outputs.push({
      id: 'output',
      name: '输出',
      type: 'any',
      description: '技能执行结果',
    })
  }

  return {
    type: `skill:${skill.name}`,
    label: skill.name,
    icon: 'ThunderboltOutlined',
    category: skill.category || 'skills',
    description: skill.description,
    subBlocks,
    inputs,
    outputs,
    source: 'skill',
    tags: skill.tags || [],
  }
}

// ==================== MCP 适配器 ====================

/**
 * 将 MCP 工具定义转换为节点定义
 */
export function adaptMCPToNode(mcp: MCPToolDefinition): NodeDefinition {
  const subBlocks: SubBlockConfig[] = []
  const inputs: NodePort[] = []
  const outputs: NodePort[] = []

  // 解析输入 schema
  if (mcp.inputSchema) {
    const properties = mcp.inputSchema.properties || mcp.inputSchema
    const required = mcp.inputSchema.required || []

    for (const [name, schema] of Object.entries(properties as Record<string, any>)) {
      const paramSchema = schema as any
      
      subBlocks.push({
        id: name,
        title: paramSchema.title || name,
        type: mapJsonSchemaToSubBlockType(paramSchema),
        description: paramSchema.description,
        required: required.includes(name),
        defaultValue: paramSchema.default,
      })

      inputs.push({
        id: name,
        name: name,
        type: mapJsonSchemaTypeToPortType(paramSchema.type),
        required: required.includes(name),
        description: paramSchema.description,
      })
    }
  }

  // 默认输出
  outputs.push({
    id: 'output',
    name: '输出',
    type: 'any',
    description: 'MCP 工具执行结果',
  })

  return {
    type: `mcp:${mcp.server}:${mcp.tool}`,
    label: `${mcp.server}/${mcp.tool}`,
    icon: 'ApiOutlined',
    category: mcp.category || 'mcp',
    description: mcp.description,
    subBlocks,
    inputs,
    outputs,
    source: 'mcp',
    tags: mcp.tags || [],
  }
}

// ==================== 批量适配 ====================

/**
 * 批量适配工具列表
 */
export function adaptTools(tools: ToolDefinition[]): NodeDefinition[] {
  return tools.map(adaptToolToNode)
}

/**
 * 批量适配技能列表
 */
export function adaptSkills(skills: SkillDefinition[]): NodeDefinition[] {
  return skills.map(adaptSkillToNode)
}

/**
 * 批量适配 MCP 工具列表
 */
export function adaptMCPTools(mcpTools: MCPToolDefinition[]): NodeDefinition[] {
  return mcpTools.map(adaptMCPToNode)
}

/**
 * 适配所有外部能力
 */
export function adaptAllCapabilities(data: {
  tools?: ToolDefinition[]
  skills?: SkillDefinition[]
  mcpTools?: MCPToolDefinition[]
}): NodeDefinition[] {
  const nodes: NodeDefinition[] = []

  if (data.tools) {
    nodes.push(...adaptTools(data.tools))
  }

  if (data.skills) {
    nodes.push(...adaptSkills(data.skills))
  }

  if (data.mcpTools) {
    nodes.push(...adaptMCPTools(data.mcpTools))
  }

  return nodes
}

// ==================== 工具函数 ====================

/**
 * 将 JSON Schema 类型映射为 SubBlock 类型
 */
function mapJsonSchemaToSubBlockType(schema: any): SubBlockConfig['type'] {
  if (schema.enum) return 'select'
  if (schema.type === 'boolean') return 'switch'
  if (schema.type === 'integer' || schema.type === 'number') {
    if (schema.minimum !== undefined && schema.maximum !== undefined) {
      return 'slider'
    }
    return 'number'
  }
  if (schema.type === 'string') {
    if (schema.format === 'date' || schema.format === 'date-time') return 'datetime'
    if (schema.format === 'color') return 'color'
    if (schema.maxLength && schema.maxLength > 500) return 'textarea'
    return 'input'
  }
  if (schema.type === 'object' || schema.type === 'array') return 'json'
  return 'input'
}

/**
 * 将 JSON Schema 类型映射为端口类型
 */
function mapJsonSchemaTypeToPortType(type: string): NodePort['type'] {
  switch (type) {
    case 'string': return 'string'
    case 'number':
    case 'integer': return 'number'
    case 'boolean': return 'boolean'
    case 'array': return 'array'
    case 'object': return 'object'
    default: return 'any'
  }
}

/**
 * 将通用类型映射为 SubBlock 类型
 */
function mapTypeToSubBlockType(type: string): SubBlockConfig['type'] {
  switch (type.toLowerCase()) {
    case 'string': return 'input'
    case 'number':
    case 'integer': return 'number'
    case 'boolean': return 'switch'
    case 'json':
    case 'object': return 'json'
    case 'array': return 'json'
    case 'text':
    case 'long_string': return 'textarea'
    case 'code': return 'code'
    case 'file': return 'file'
    case 'date': return 'date'
    case 'time': return 'time'
    case 'datetime': return 'datetime'
    case 'color': return 'color'
    default: return 'input'
  }
}

/**
 * 将通用类型映射为端口类型
 */
function mapTypeToPortType(type: string): NodePort['type'] {
  switch (type.toLowerCase()) {
    case 'string':
    case 'text':
    case 'long_string': return 'string'
    case 'number':
    case 'integer': return 'number'
    case 'boolean': return 'boolean'
    case 'json':
    case 'object': return 'object'
    case 'array': return 'array'
    default: return 'any'
  }
}

// ==================== 从后端加载 ====================

/**
 * 从后端加载并适配所有节点
 */
export async function loadAndAdaptNodes(): Promise<NodeDefinition[]> {
  try {
    const response = await fetch('/api/v1/neurflow/nodes')
    const data = await response.json()
    
    // 后端已经返回了适配后的节点定义
    return data.nodes as NodeDefinition[]
  } catch (error) {
    console.error('Failed to load nodes:', error)
    return []
  }
}

/**
 * 从后端加载工具并适配
 */
export async function loadAndAdaptTools(): Promise<NodeDefinition[]> {
  try {
    const response = await fetch('/api/v1/tools')
    const data = await response.json()
    
    return adaptTools(data.tools)
  } catch (error) {
    console.error('Failed to load tools:', error)
    return []
  }
}

/**
 * 从后端加载技能并适配
 */
export async function loadAndAdaptSkills(): Promise<NodeDefinition[]> {
  try {
    const response = await fetch('/api/v1/skills')
    const data = await response.json()
    
    return adaptSkills(data.skills)
  } catch (error) {
    console.error('Failed to load skills:', error)
    return []
  }
}