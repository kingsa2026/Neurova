/**
 * Neurflow 节点注册表
 * 管理前端节点定义，支持动态加载和查询
 */

import type {
  NodeDefinition,
  NodeCategory,
  NodeSource,
  NodeRegistry,
  NodeFactory,
  EdgeFactory,
  WorkflowNode,
  WorkflowEdge,
} from './types'

// ==================== 节点注册表实现 ====================

class NodeRegistryImpl implements NodeRegistry {
  nodes = new Map<string, NodeDefinition>()
  categories = new Map<string, NodeDefinition[]>()

  /**
   * 注册节点定义
   */
  register(definition: NodeDefinition): void {
    // 验证必填字段
    if (!definition.type) {
      throw new Error('Node definition must have a type')
    }
    if (!definition.label) {
      throw new Error('Node definition must have a label')
    }
    if (!definition.category) {
      throw new Error('Node definition must have a category')
    }

    // 注册到主映射
    this.nodes.set(definition.type, definition)

    // 注册到分类映射
    const categoryNodes = this.categories.get(definition.category) || []
    const existingIndex = categoryNodes.findIndex(n => n.type === definition.type)
    
    if (existingIndex >= 0) {
      categoryNodes[existingIndex] = definition
    } else {
      categoryNodes.push(definition)
    }
    this.categories.set(definition.category, categoryNodes)

    // 触发注册事件
    this.emit('register', definition)
  }

  /**
   * 注销节点定义
   */
  unregister(type: string): void {
    const definition = this.nodes.get(type)
    if (!definition) {
      return
    }

    // 从主映射移除
    this.nodes.delete(type)

    // 从分类映射移除
    const categoryNodes = this.categories.get(definition.category) || []
    const index = categoryNodes.findIndex(n => n.type === type)
    if (index >= 0) {
      categoryNodes.splice(index, 1)
    }

    // 触发注销事件
    this.emit('unregister', definition)
  }

  /**
   * 获取节点定义
   */
  get(type: string): NodeDefinition | undefined {
    return this.nodes.get(type)
  }

  /**
   * 获取指定分类的节点
   */
  getByCategory(category: string): NodeDefinition[] {
    return this.categories.get(category) || []
  }

  /**
   * 获取指定来源的节点
   */
  getBySource(source: NodeSource): NodeDefinition[] {
    return Array.from(this.nodes.values()).filter(n => n.source === source)
  }

  /**
   * 搜索节点
   */
  search(query: string): NodeDefinition[] {
    const lowerQuery = query.toLowerCase()
    return Array.from(this.nodes.values()).filter(node => {
      // 搜索标签
      if (node.label.toLowerCase().includes(lowerQuery)) {
        return true
      }
      // 搜索描述
      if (node.description?.toLowerCase().includes(lowerQuery)) {
        return true
      }
      // 搜索类型
      if (node.type.toLowerCase().includes(lowerQuery)) {
        return true
      }
      // 搜索标签
      if (node.tags?.some(tag => tag.toLowerCase().includes(lowerQuery))) {
        return true
      }
      return false
    })
  }

  /**
   * 获取所有节点
   */
  getAll(): NodeDefinition[] {
    return Array.from(this.nodes.values())
  }

  /**
   * 清空注册表
   */
  clear(): void {
    this.nodes.clear()
    this.categories.clear()
    this.emit('clear')
  }

  /**
   * 获取所有分类
   */
  getCategories(): string[] {
    return Array.from(this.categories.keys())
  }

  /**
   * 获取节点数量
   */
  get size(): number {
    return this.nodes.size
  }

  /**
   * 检查节点是否存在
   */
  has(type: string): boolean {
    return this.nodes.has(type)
  }

  /**
   * 批量注册节点
   */
  registerBatch(definitions: NodeDefinition[]): void {
    definitions.forEach(def => this.register(def))
  }

  /**
   * 批量注销节点
   */
  unregisterBatch(types: string[]): void {
    types.forEach(type => this.unregister(type))
  }

  /**
   * 导出为 JSON
   */
  toJSON(): NodeDefinition[] {
    return Array.from(this.nodes.values())
  }

  /**
   * 从 JSON 导入
   */
  fromJSON(data: NodeDefinition[]): void {
    this.clear()
    this.registerBatch(data)
  }

  /**
   * 事件发射器（简化版）
   */
  private listeners = new Map<string, Set<Function>>()

  on(event: string, listener: Function): void {
    if (!this.listeners.has(event)) {
      this.listeners.set(event, new Set())
    }
    this.listeners.get(event)!.add(listener)
  }

  off(event: string, listener: Function): void {
    this.listeners.get(event)?.delete(listener)
  }

  private emit(event: string, ...args: any[]): void {
    this.listeners.get(event)?.forEach(listener => {
      try {
        listener(...args)
      } catch (error) {
        console.error(`Error in registry event listener for ${event}:`, error)
      }
    })
  }
}

// ==================== 单例实例 ====================

export const nodeRegistry = new NodeRegistryImpl()

// ==================== 工厂函数 ====================

/**
 * 创建节点工厂
 */
export function createNodeFactory(
  registry: NodeRegistry,
  defaultPosition: { x: number; y: number } = { x: 0, y: 0 }
): NodeFactory {
  return (position = defaultPosition, data = {}) => {
    // 这里需要指定节点类型，返回一个工厂函数
    // 实际使用时需要传入节点类型
    return {
      id: `node_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
      type: 'unknown', // 需要从外部指定
      label: 'New Node',
      position,
      data,
      inputs: {},
      outputs: {},
    }
  }
}

/**
 * 创建边工厂
 */
export function createEdgeFactory(): EdgeFactory {
  return (source, target, sourceHandle, targetHandle) => ({
    id: `edge_${source}_${target}_${Date.now()}`,
    source,
    target,
    sourceHandle,
    targetHandle,
    type: 'smoothstep',
    animated: false,
  })
}

// ==================== 默认节点定义 ====================

/**
 * 注册默认内置节点
 */
export function registerDefaultNodes(): void {
  // 输入节点
  nodeRegistry.register({
    type: 'input',
    label: '输入',
    icon: 'input',
    category: 'input',
    description: '工作流输入节点',
    source: 'builtin',
    tags: ['input', 'start'],
    subBlocks: [
      {
        id: 'value',
        title: '输入值',
        type: 'input',
        required: true,
        description: '工作流的输入数据',
      },
    ],
    inputs: [],
    outputs: [
      {
        id: 'output',
        name: '输出',
        type: 'any',
        description: '输入的数据',
      },
    ],
  })

  // 输出节点
  nodeRegistry.register({
    type: 'output',
    label: '输出',
    icon: 'output',
    category: 'output',
    description: '工作流输出节点',
    source: 'builtin',
    tags: ['output', 'end'],
    subBlocks: [
      {
        id: 'value',
        title: '输出值',
        type: 'input',
        required: true,
        description: '工作流的输出数据',
      },
    ],
    inputs: [
      {
        id: 'input',
        name: '输入',
        type: 'any',
        description: '要输出的数据',
      },
    ],
    outputs: [],
  })

  // LLM 节点
  nodeRegistry.register({
    type: 'llm',
    label: 'LLM',
    icon: 'robot',
    category: 'llm',
    description: '大语言模型调用节点',
    source: 'builtin',
    tags: ['llm', 'ai', 'chat', 'completion'],
    subBlocks: [
      {
        id: 'model',
        title: '模型',
        type: 'model-selector',
        required: true,
        description: '选择要使用的模型',
      },
      {
        id: 'prompt',
        title: '提示词',
        type: 'textarea',
        required: true,
        description: '发送给模型的提示词',
        language: 'markdown',
      },
      {
        id: 'temperature',
        title: '温度',
        type: 'slider',
        min: 0,
        max: 2,
        step: 0.1,
        defaultValue: 0.7,
        description: '生成文本的随机性',
      },
      {
        id: 'maxTokens',
        title: '最大 Token 数',
        type: 'number',
        min: 1,
        max: 128000,
        defaultValue: 4096,
        description: '生成的最大 token 数量',
      },
    ],
    inputs: [
      {
        id: 'prompt',
        name: '提示词',
        type: 'string',
        description: '动态提示词输入',
      },
      {
        id: 'context',
        name: '上下文',
        type: 'string',
        description: '额外上下文信息',
      },
    ],
    outputs: [
      {
        id: 'response',
        name: '响应',
        type: 'string',
        description: '模型生成的响应',
      },
      {
        id: 'usage',
        name: '用量',
        type: 'object',
        description: 'Token 使用统计',
      },
    ],
  })

  // 条件节点
  nodeRegistry.register({
    type: 'condition',
    label: '条件',
    icon: 'branch',
    category: 'control',
    description: '条件分支节点',
    source: 'builtin',
    tags: ['condition', 'branch', 'if', 'control'],
    subBlocks: [
      {
        id: 'field',
        title: '字段',
        type: 'input',
        required: true,
        description: '要检查的字段路径',
      },
      {
        id: 'operator',
        title: '运算符',
        type: 'select',
        required: true,
        options: [
          { label: '等于', value: 'eq' },
          { label: '不等于', value: 'ne' },
          { label: '大于', value: 'gt' },
          { label: '小于', value: 'lt' },
          { label: '大于等于', value: 'gte' },
          { label: '小于等于', value: 'lte' },
          { label: '包含', value: 'contains' },
          { label: '不包含', value: 'not_contains' },
          { label: '为空', value: 'empty' },
          { label: '不为空', value: 'not_empty' },
        ],
        description: '比较运算符',
      },
      {
        id: 'value',
        title: '比较值',
        type: 'input',
        description: '要比较的值',
      },
    ],
    inputs: [
      {
        id: 'input',
        name: '输入',
        type: 'any',
        description: '要判断的数据',
      },
    ],
    outputs: [
      {
        id: 'true',
        name: '真',
        type: 'any',
        description: '条件为真时的输出',
      },
      {
        id: 'false',
        name: '假',
        type: 'any',
        description: '条件为假时的输出',
      },
    ],
  })

  // 循环节点
  nodeRegistry.register({
    type: 'loop',
    label: '循环',
    icon: 'sync',
    category: 'control',
    description: '循环执行节点',
    source: 'builtin',
    tags: ['loop', 'iterate', 'repeat', 'control'],
    subBlocks: [
      {
        id: 'type',
        title: '循环类型',
        type: 'select',
        required: true,
        options: [
          { label: '遍历数组', value: 'each' },
          { label: '条件循环', value: 'while' },
          { label: '固定次数', value: 'count' },
        ],
        description: '循环的类型',
      },
      {
        id: 'maxIterations',
        title: '最大迭代次数',
        type: 'number',
        min: 1,
        max: 10000,
        defaultValue: 100,
        description: '防止无限循环的最大迭代次数',
      },
    ],
    inputs: [
      {
        id: 'collection',
        name: '集合',
        type: 'array',
        description: '要遍历的集合',
      },
      {
        id: 'condition',
        name: '条件',
        type: 'boolean',
        description: '循环条件',
      },
    ],
    outputs: [
      {
        id: 'item',
        name: '当前项',
        type: 'any',
        description: '当前迭代的元素',
      },
      {
        id: 'index',
        name: '索引',
        type: 'number',
        description: '当前迭代的索引',
      },
      {
        id: 'result',
        name: '结果',
        type: 'array',
        description: '循环结果数组',
      },
    ],
  })

  // 记忆搜索节点
  nodeRegistry.register({
    type: 'memory_search',
    label: '记忆搜索',
    icon: 'search',
    category: 'memory',
    description: '搜索 Neurova 记忆系统',
    source: 'builtin',
    tags: ['memory', 'search', 'recall', 'knowledge'],
    subBlocks: [
      {
        id: 'query',
        title: '查询',
        type: 'textarea',
        required: true,
        description: '搜索查询文本',
      },
      {
        id: 'limit',
        title: '结果数量',
        type: 'number',
        min: 1,
        max: 100,
        defaultValue: 10,
        description: '返回的最大结果数',
      },
      {
        id: 'threshold',
        title: '相似度阈值',
        type: 'slider',
        min: 0,
        max: 1,
        step: 0.01,
        defaultValue: 0.7,
        description: '相似度阈值（0-1）',
      },
    ],
    inputs: [
      {
        id: 'query',
        name: '查询',
        type: 'string',
        description: '动态查询输入',
      },
    ],
    outputs: [
      {
        id: 'results',
        name: '结果',
        type: 'array',
        description: '搜索结果列表',
      },
      {
        id: 'count',
        name: '数量',
        type: 'number',
        description: '结果数量',
      },
    ],
  })

  // 代码执行节点
  nodeRegistry.register({
    type: 'code',
    label: '代码',
    icon: 'code',
    category: 'tool',
    description: '执行自定义代码',
    source: 'builtin',
    tags: ['code', 'javascript', 'python', 'execute'],
    subBlocks: [
      {
        id: 'language',
        title: '语言',
        type: 'select',
        required: true,
        options: [
          { label: 'JavaScript', value: 'javascript' },
          { label: 'Python', value: 'python' },
        ],
        defaultValue: 'javascript',
        description: '编程语言',
      },
      {
        id: 'code',
        title: '代码',
        type: 'code',
        required: true,
        language: 'javascript',
        description: '要执行的代码',
      },
      {
        id: 'timeout',
        title: '超时（毫秒）',
        type: 'number',
        min: 1000,
        max: 300000,
        defaultValue: 30000,
        description: '执行超时时间',
      },
    ],
    inputs: [
      {
        id: 'input',
        name: '输入',
        type: 'any',
        description: '代码输入数据',
      },
    ],
    outputs: [
      {
        id: 'output',
        name: '输出',
        type: 'any',
        description: '代码执行结果',
      },
      {
        id: 'error',
        name: '错误',
        type: 'string',
        description: '执行错误信息',
      },
    ],
  })

  // HTTP 请求节点
  nodeRegistry.register({
    type: 'http',
    label: 'HTTP',
    icon: 'global',
    category: 'integration',
    description: '发送 HTTP 请求',
    source: 'builtin',
    tags: ['http', 'api', 'request', 'rest'],
    subBlocks: [
      {
        id: 'method',
        title: '方法',
        type: 'select',
        required: true,
        options: [
          { label: 'GET', value: 'GET' },
          { label: 'POST', value: 'POST' },
          { label: 'PUT', value: 'PUT' },
          { label: 'DELETE', value: 'DELETE' },
          { label: 'PATCH', value: 'PATCH' },
        ],
        defaultValue: 'GET',
        description: 'HTTP 请求方法',
      },
      {
        id: 'url',
        title: 'URL',
        type: 'input',
        required: true,
        description: '请求 URL',
      },
      {
        id: 'headers',
        title: '请求头',
        type: 'json',
        description: '请求头（JSON 格式）',
      },
      {
        id: 'body',
        title: '请求体',
        type: 'json',
        description: '请求体（JSON 格式）',
      },
    ],
    inputs: [
      {
        id: 'url',
        name: 'URL',
        type: 'string',
        description: '动态 URL 输入',
      },
      {
        id: 'body',
        name: '请求体',
        type: 'object',
        description: '动态请求体',
      },
    ],
    outputs: [
      {
        id: 'response',
        name: '响应',
        type: 'object',
        description: 'HTTP 响应',
      },
      {
        id: 'status',
        name: '状态码',
        type: 'number',
        description: 'HTTP 状态码',
      },
      {
        id: 'data',
        name: '数据',
        type: 'any',
        description: '响应数据',
      },
    ],
  })

  // 等待节点
  nodeRegistry.register({
    type: 'wait',
    label: '等待',
    icon: 'clock',
    category: 'control',
    description: '等待指定时间',
    source: 'builtin',
    tags: ['wait', 'delay', 'sleep', 'timer'],
    subBlocks: [
      {
        id: 'duration',
        title: '等待时间（毫秒）',
        type: 'number',
        min: 0,
        max: 3600000,
        defaultValue: 1000,
        required: true,
        description: '等待的时间（毫秒）',
      },
    ],
    inputs: [
      {
        id: 'input',
        name: '输入',
        type: 'any',
        description: '等待期间传递的数据',
      },
    ],
    outputs: [
      {
        id: 'output',
        name: '输出',
        type: 'any',
        description: '等待结束后输出的数据',
      },
    ],
  })

  // 人工审批节点
  nodeRegistry.register({
    type: 'human_approval',
    label: '人工审批',
    icon: 'user',
    category: 'control',
    description: '需要人工审批才能继续',
    source: 'builtin',
    tags: ['human', 'approval', 'review', 'manual'],
    subBlocks: [
      {
        id: 'message',
        title: '审批消息',
        type: 'textarea',
        required: true,
        description: '显示给审批者的消息',
      },
      {
        id: 'timeout',
        title: '超时（毫秒）',
        type: 'number',
        min: 0,
        max: 86400000,
        defaultValue: 3600000,
        description: '审批超时时间（0 表示不限）',
      },
      {
        id: 'approvers',
        title: '审批人',
        type: 'input',
        description: '审批人列表（逗号分隔）',
      },
    ],
    inputs: [
      {
        id: 'data',
        name: '数据',
        type: 'any',
        description: '需要审批的数据',
      },
    ],
    outputs: [
      {
        id: 'approved',
        name: '批准',
        type: 'any',
        description: '审批通过的数据',
      },
      {
        id: 'rejected',
        name: '拒绝',
        type: 'any',
        description: '审批拒绝的数据',
      },
      {
        id: 'comment',
        name: '审批意见',
        type: 'string',
        description: '审批者的评论',
      },
    ],
  })

  // 变量赋值节点
  nodeRegistry.register({
    type: 'set_variable',
    label: '设置变量',
    icon: 'setting',
    category: 'data',
    description: '设置工作流变量',
    source: 'builtin',
    tags: ['variable', 'set', 'assign', 'data'],
    subBlocks: [
      {
        id: 'name',
        title: '变量名',
        type: 'input',
        required: true,
        description: '要设置的变量名',
      },
      {
        id: 'value',
        title: '变量值',
        type: 'input',
        required: true,
        description: '变量的值',
      },
      {
        id: 'scope',
        title: '作用域',
        type: 'select',
        options: [
          { label: '全局', value: 'global' },
          { label: '局部', value: 'local' },
        ],
        defaultValue: 'global',
        description: '变量的作用域',
      },
    ],
    inputs: [
      {
        id: 'input',
        name: '输入',
        type: 'any',
        description: '触发赋值的数据',
      },
    ],
    outputs: [
      {
        id: 'output',
        name: '输出',
        type: 'any',
        description: '赋值后的数据',
      },
    ],
  })

  // 数据转换节点
  nodeRegistry.register({
    type: 'transform',
    label: '数据转换',
    icon: 'swap',
    category: 'data',
    description: '转换数据格式',
    source: 'builtin',
    tags: ['transform', 'convert', 'format', 'data'],
    subBlocks: [
      {
        id: 'operation',
        title: '操作',
        type: 'select',
        required: true,
        options: [
          { label: 'JSON 解析', value: 'json_parse' },
          { label: 'JSON 序列化', value: 'json_stringify' },
          { label: '提取字段', value: 'extract' },
          { label: '合并对象', value: 'merge' },
          { label: '数组扁平化', value: 'flatten' },
          { label: '去重', value: 'unique' },
          { label: '排序', value: 'sort' },
          { label: '过滤', value: 'filter' },
          { label: '映射', value: 'map' },
        ],
        description: '转换操作类型',
      },
      {
        id: 'expression',
        title: '表达式',
        type: 'input',
        description: '转换表达式',
      },
    ],
    inputs: [
      {
        id: 'input',
        name: '输入',
        type: 'any',
        description: '要转换的数据',
      },
    ],
    outputs: [
      {
        id: 'output',
        name: '输出',
        type: 'any',
        description: '转换后的数据',
      },
    ],
  })

  console.log(`Registered ${nodeRegistry.size} default nodes`)
}

// ==================== 工具函数 ====================

/**
 * 从后端加载节点定义
 */
export async function loadNodesFromBackend(): Promise<void> {
  try {
    const response = await fetch('/api/v1/neurflow/nodes')
    if (!response.ok) {
      throw new Error(`Failed to load nodes: ${response.statusText}`)
    }
    
    const data = await response.json()
    const nodes: NodeDefinition[] = data.nodes || []
    
    // 注册后端节点
    nodeRegistry.registerBatch(nodes)
    
    console.log(`Loaded ${nodes.length} nodes from backend`)
  } catch (error) {
    console.error('Failed to load nodes from backend:', error)
    // 使用默认节点
    registerDefaultNodes()
  }
}

/**
 * 初始化节点注册表
 */
export async function initializeNodeRegistry(): Promise<void> {
  // 先注册默认节点
  registerDefaultNodes()
  
  // 然后尝试从后端加载
  await loadNodesFromBackend()
}

/**
 * 获取节点图标
 */
export function getNodeIcon(node: NodeDefinition): string {
  if (node.icon) {
    return node.icon
  }
  
  // 根据类别返回默认图标
  const categoryIcons: Record<string, string> = {
    input: 'input',
    output: 'output',
    llm: 'robot',
    tool: 'tool',
    skill: 'thunderbolt',
    control: 'branch',
    data: 'database',
    memory: 'brain',
    evolution: 'line-chart',
    tdd: 'bug',
    media: 'play-circle',
    integration: 'api',
    custom: 'block',
  }
  
  return categoryIcons[node.category] || 'block'
}

/**
 * 获取节点颜色
 */
export function getNodeColor(node: NodeDefinition): string {
  if (node.color) {
    return node.color
  }
  
  // 根据类别返回默认颜色
  const categoryColors: Record<string, string> = {
    input: '#52c41a',
    output: '#faad14',
    llm: '#722ed1',
    tool: '#1890ff',
    skill: '#13c2c2',
    control: '#eb2f96',
    data: '#fa8c16',
    memory: '#2f54eb',
    evolution: '#a0d911',
    tdd: '#f5222d',
    media: '#722ed1',
    integration: '#1890ff',
    custom: '#8c8c8c',
  }
  
  return categoryColors[node.category] || '#8c8c8c'
}

/**
 * 验证节点定义
 */
export function validateNodeDefinition(node: NodeDefinition): string[] {
  const errors: string[] = []
  
  if (!node.type) {
    errors.push('Node type is required')
  }
  if (!node.label) {
    errors.push('Node label is required')
  }
  if (!node.category) {
    errors.push('Node category is required')
  }
  if (!node.source) {
    errors.push('Node source is required')
  }
  
  // 验证端口
  node.inputs?.forEach((port, index) => {
    if (!port.id) {
      errors.push(`Input port ${index} must have an id`)
    }
    if (!port.name) {
      errors.push(`Input port ${index} must have a name`)
    }
  })
  
  node.outputs?.forEach((port, index) => {
    if (!port.id) {
      errors.push(`Output port ${index} must have an id`)
    }
    if (!port.name) {
      errors.push(`Output port ${index} must have a name`)
    }
  })
  
  return errors
}

// ==================== 导出 ====================

export default nodeRegistry
