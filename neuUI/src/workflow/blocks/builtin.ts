/**
 * 内置节点 UI 定义
 * 定义所有内置节点的参数配置界面
 */

import type { SubBlockConfig } from '../types'

// 节点 UI 定义接口
export interface NodeUIDefinition {
  type: string
  label: string
  icon: string
  category: string
  description: string
  subBlocks: SubBlockConfig[]
  defaultData: Record<string, any>
}

// 内置节点 UI 定义
export const builtinNodeUIDefinitions: NodeUIDefinition[] = [
  // ==================== 输入节点 ====================
  {
    type: 'builtin:input',
    label: '用户输入',
    icon: 'MessageOutlined',
    category: 'input',
    description: '接收用户输入数据',
    subBlocks: [
      {
        id: 'description',
        title: '输入描述',
        type: 'input',
        placeholder: '请输入描述',
        description: '提示用户输入什么内容',
      },
      {
        id: 'required',
        title: '是否必填',
        type: 'switch',
        defaultValue: true,
      },
      {
        id: 'validation',
        title: '验证规则',
        type: 'textarea',
        placeholder: '正则表达式或自定义验证',
        description: '可选，用于验证用户输入',
      },
    ],
    defaultData: {
      description: '请输入内容',
      required: true,
    },
  },

  // ==================== 输出节点 ====================
  {
    type: 'builtin:output',
    label: '输出结果',
    icon: 'ExportOutlined',
    category: 'output',
    description: '输出工作流结果',
    subBlocks: [
      {
        id: 'description',
        title: '输出描述',
        type: 'input',
        placeholder: '请输入描述',
      },
      {
        id: 'format',
        title: '输出格式',
        type: 'select',
        options: [
          { label: '文本', value: 'text' },
          { label: 'JSON', value: 'json' },
          { label: 'Markdown', value: 'markdown' },
          { label: 'HTML', value: 'html' },
        ],
        defaultValue: 'text',
      },
      {
        id: 'template',
        title: '输出模板',
        type: 'textarea',
        placeholder: '使用 {{variable}} 引用变量',
        description: '可选，自定义输出格式',
      },
    ],
    defaultData: {
      description: '输出结果',
      format: 'text',
    },
  },

  // ==================== LLM 节点 ====================
  {
    type: 'builtin:llm',
    label: 'LLM 调用',
    icon: 'RobotOutlined',
    category: 'ai',
    description: '调用大语言模型',
    subBlocks: [
      {
        id: 'model',
        title: '模型',
        type: 'model-selector',
        description: '选择要使用的模型',
        providerCapability: 'text',
      },
      {
        id: 'prompt',
        title: '提示词',
        type: 'textarea',
        required: true,
        placeholder: '请输入提示词，支持 {{variable}} 引用变量',
        description: '发送给模型的提示词',
      },
      {
        id: 'system_prompt',
        title: '系统提示词',
        type: 'textarea',
        placeholder: '可选，定义模型的行为和角色',
      },
      {
        id: 'temperature',
        title: '温度',
        type: 'slider',
        min: 0,
        max: 2,
        defaultValue: 0.7,
        description: '控制输出的随机性',
      },
      {
        id: 'max_tokens',
        title: '最大 Token 数',
        type: 'number',
        min: 1,
        max: 128000,
        defaultValue: 4096,
      },
      {
        id: 'stream',
        title: '流式输出',
        type: 'switch',
        defaultValue: true,
      },
      {
        id: 'tools',
        title: '可用工具',
        type: 'json',
        description: '可选，定义模型可调用的工具',
      },
    ],
    defaultData: {
      temperature: 0.7,
      max_tokens: 4096,
      stream: true,
    },
  },

  // ==================== 条件节点 ====================
  {
    type: 'builtin:condition',
    label: '条件判断',
    icon: 'BranchesOutlined',
    category: 'control',
    description: '根据条件分支执行',
    subBlocks: [
      {
        id: 'expression',
        title: '条件表达式',
        type: 'textarea',
        required: true,
        placeholder: '{{variable}} === "value"',
        description: '返回 true/false 的表达式',
      },
      {
        id: 'operator',
        title: '运算符',
        type: 'select',
        options: [
          { label: '等于 (===)', value: '===' },
          { label: '不等于 (!==)', value: '!==' },
          { label: '大于 (>)', value: '>' },
          { label: '小于 (<)', value: '<' },
          { label: '包含', value: 'includes' },
          { label: '正则匹配', value: 'regex' },
        ],
        defaultValue: '===',
      },
    ],
    defaultData: {
      expression: '',
      operator: '===',
    },
  },

  // ==================== 循环节点 ====================
  {
    type: 'builtin:loop',
    label: '循环',
    icon: 'ReloadOutlined',
    category: 'control',
    description: '循环执行子流程',
    subBlocks: [
      {
        id: 'loopType',
        title: '循环类型',
        type: 'select',
        options: [
          { label: '次数循环', value: 'count' },
          { label: '条件循环', value: 'while' },
          { label: '遍历数组', value: 'foreach' },
        ],
        defaultValue: 'count',
      },
      {
        id: 'count',
        title: '循环次数',
        type: 'number',
        min: 1,
        max: 1000,
        defaultValue: 10,
        condition: { field: 'loopType', operator: '===', value: 'count' },
      },
      {
        id: 'condition',
        title: '循环条件',
        type: 'textarea',
        placeholder: '返回 true 继续循环',
        condition: { field: 'loopType', operator: '===', value: 'while' },
      },
      {
        id: 'collection',
        title: '遍历数组',
        type: 'textarea',
        placeholder: '{{array_variable}}',
        condition: { field: 'loopType', operator: '===', value: 'foreach' },
      },
      {
        id: 'maxIterations',
        title: '最大迭代次数',
        type: 'number',
        min: 1,
        max: 10000,
        defaultValue: 100,
        description: '防止无限循环',
      },
    ],
    defaultData: {
      loopType: 'count',
      count: 10,
      maxIterations: 100,
    },
  },

  // ==================== 记忆搜索节点 ====================
  {
    type: 'builtin:memory_search',
    label: '记忆搜索',
    icon: 'SearchOutlined',
    category: 'memory',
    description: '搜索记忆库',
    subBlocks: [
      {
        id: 'query',
        title: '搜索查询',
        type: 'textarea',
        required: true,
        placeholder: '搜索关键词或问题',
      },
      {
        id: 'limit',
        title: '结果数量',
        type: 'number',
        min: 1,
        max: 100,
        defaultValue: 10,
      },
      {
        id: 'threshold',
        title: '相似度阈值',
        type: 'slider',
        min: 0,
        max: 1,
        defaultValue: 0.7,
        description: '只返回相似度高于此值的结果',
      },
      {
        id: 'filters',
        title: '过滤条件',
        type: 'json',
        description: '可选，按标签、时间等过滤',
      },
    ],
    defaultData: {
      limit: 10,
      threshold: 0.7,
    },
  },

  // ==================== 记忆保存节点 ====================
  {
    type: 'builtin:memory_save',
    label: '记忆保存',
    icon: 'SaveOutlined',
    category: 'memory',
    description: '保存数据到记忆库',
    subBlocks: [
      {
        id: 'content',
        title: '保存内容',
        type: 'textarea',
        required: true,
        placeholder: '要保存的内容，支持 {{variable}}',
      },
      {
        id: 'tags',
        title: '标签',
        type: 'input',
        placeholder: '标签1, 标签2',
        description: '用逗号分隔的标签',
      },
      {
        id: 'importance',
        title: '重要性',
        type: 'slider',
        min: 0,
        max: 1,
        defaultValue: 0.5,
      },
      {
        id: 'type',
        title: '记忆类型',
        type: 'select',
        options: [
          { label: '事实', value: 'fact' },
          { label: '经验', value: 'experience' },
          { label: '偏好', value: 'preference' },
          { label: '事件', value: 'event' },
        ],
        defaultValue: 'fact',
      },
    ],
    defaultData: {
      importance: 0.5,
      type: 'fact',
    },
  },

  // ==================== 代码执行节点 ====================
  {
    type: 'builtin:code',
    label: '代码执行',
    icon: 'CodeOutlined',
    category: 'utility',
    description: '执行自定义代码',
    subBlocks: [
      {
        id: 'language',
        title: '编程语言',
        type: 'select',
        options: [
          { label: 'Python', value: 'python' },
          { label: 'JavaScript', value: 'javascript' },
          { label: 'TypeScript', value: 'typescript' },
        ],
        defaultValue: 'python',
      },
      {
        id: 'code',
        title: '代码',
        type: 'code',
        required: true,
        language: 'python',
        placeholder: '# 在这里编写代码\n# 输入变量通过 input_dict 获取\nresult = input_dict["value"] * 2',
      },
      {
        id: 'timeout',
        title: '超时时间 (秒)',
        type: 'number',
        min: 1,
        max: 300,
        defaultValue: 30,
      },
      {
        id: 'sandbox',
        title: '沙箱模式',
        type: 'switch',
        defaultValue: true,
        description: '在沙箱环境中执行代码',
      },
    ],
    defaultData: {
      language: 'python',
      timeout: 30,
      sandbox: true,
    },
  },

  // ==================== HTTP 请求节点 ====================
  {
    type: 'builtin:http',
    label: 'HTTP 请求',
    icon: 'GlobalOutlined',
    category: 'utility',
    description: '发送 HTTP 请求',
    subBlocks: [
      {
        id: 'method',
        title: '请求方法',
        type: 'select',
        options: [
          { label: 'GET', value: 'GET' },
          { label: 'POST', value: 'POST' },
          { label: 'PUT', value: 'PUT' },
          { label: 'DELETE', value: 'DELETE' },
          { label: 'PATCH', value: 'PATCH' },
        ],
        defaultValue: 'GET',
      },
      {
        id: 'url',
        title: '请求 URL',
        type: 'input',
        required: true,
        placeholder: 'https://api.example.com/endpoint',
      },
      {
        id: 'headers',
        title: '请求头',
        type: 'json',
        placeholder: '{"Content-Type": "application/json"}',
      },
      {
        id: 'body',
        title: '请求体',
        type: 'textarea',
        placeholder: 'JSON 请求体',
        condition: { field: 'method', operator: '!==', value: 'GET' },
      },
      {
        id: 'timeout',
        title: '超时时间 (秒)',
        type: 'number',
        min: 1,
        max: 300,
        defaultValue: 30,
      },
    ],
    defaultData: {
      method: 'GET',
      timeout: 30,
    },
  },

  // ==================== 等待节点 ====================
  {
    type: 'builtin:wait',
    label: '等待',
    icon: 'ClockOutlined',
    category: 'control',
    description: '等待指定时间',
    subBlocks: [
      {
        id: 'duration',
        title: '等待时间 (毫秒)',
        type: 'number',
        min: 100,
        max: 3600000,
        defaultValue: 1000,
      },
      {
        id: 'reason',
        title: '等待原因',
        type: 'input',
        placeholder: '可选，说明为什么等待',
      },
    ],
    defaultData: {
      duration: 1000,
    },
  },

  // ==================== 人工审批节点 ====================
  {
    type: 'builtin:human_approval',
    label: '人工审批',
    icon: 'UserOutlined',
    category: 'control',
    description: '等待人工审批',
    subBlocks: [
      {
        id: 'message',
        title: '审批消息',
        type: 'textarea',
        required: true,
        placeholder: '发送给审批者的消息',
      },
      {
        id: 'approvers',
        title: '审批者',
        type: 'input',
        placeholder: '用户ID或角色',
        description: '可选，指定审批者',
      },
      {
        id: 'timeout',
        title: '超时时间 (小时)',
        type: 'number',
        min: 1,
        max: 168,
        defaultValue: 24,
      },
      {
        id: 'autoApprove',
        title: '超时自动批准',
        type: 'switch',
        defaultValue: false,
      },
    ],
    defaultData: {
      timeout: 24,
      autoApprove: false,
    },
  },

  // ==================== 设置变量节点 ====================
  {
    type: 'builtin:set_variable',
    label: '设置变量',
    icon: 'SwapOutlined',
    category: 'utility',
    description: '设置或修改工作流变量',
    subBlocks: [
      {
        id: 'variableName',
        title: '变量名',
        type: 'input',
        required: true,
        placeholder: 'my_variable',
      },
      {
        id: 'value',
        title: '变量值',
        type: 'textarea',
        required: true,
        placeholder: '值，支持 {{variable}} 引用',
      },
      {
        id: 'scope',
        title: '作用域',
        type: 'select',
        options: [
          { label: '工作流', value: 'workflow' },
          { label: '节点', value: 'node' },
          { label: '全局', value: 'global' },
        ],
        defaultValue: 'workflow',
      },
    ],
    defaultData: {
      scope: 'workflow',
    },
  },

  // ==================== 数据转换节点 ====================
  {
    type: 'builtin:transform',
    label: '数据转换',
    icon: 'FunctionOutlined',
    category: 'utility',
    description: '转换数据格式',
    subBlocks: [
      {
        id: 'input',
        title: '输入数据',
        type: 'textarea',
        required: true,
        placeholder: '{{input_variable}}',
      },
      {
        id: 'transformType',
        title: '转换类型',
        type: 'select',
        options: [
          { label: 'JSON 解析', value: 'json_parse' },
          { label: 'JSON 字符串化', value: 'json_stringify' },
          { label: '提取字段', value: 'extract' },
          { label: '映射', value: 'map' },
          { label: '过滤', value: 'filter' },
          { label: '排序', value: 'sort' },
          { label: '自定义表达式', value: 'expression' },
        ],
        defaultValue: 'json_parse',
      },
      {
        id: 'expression',
        title: '转换表达式',
        type: 'textarea',
        placeholder: 'data.map(item => item.name)',
        condition: { field: 'transformType', operator: '===', value: 'expression' },
      },
      {
        id: 'field',
        title: '提取字段',
        type: 'input',
        placeholder: 'data.nested.field',
        condition: { field: 'transformType', operator: '===', value: 'extract' },
      },
    ],
    defaultData: {
      transformType: 'json_parse',
    },
  },

  // ==================== 情感分析节点 ====================
  {
    type: 'builtin:emotion',
    label: '情感分析',
    icon: 'HeartOutlined',
    category: 'ai',
    description: '分析文本情感',
    subBlocks: [
      {
        id: 'text',
        title: '分析文本',
        type: 'textarea',
        required: true,
        placeholder: '要分析的文本，支持 {{variable}}',
      },
      {
        id: 'granularity',
        title: '分析粒度',
        type: 'select',
        options: [
          { label: '简单 (正/负/中)', value: 'simple' },
          { label: '详细 (17种情感)', value: 'detailed' },
        ],
        defaultValue: 'simple',
      },
    ],
    defaultData: {
      granularity: 'simple',
    },
  },

  // ==================== 进化反馈节点 ====================
  {
    type: 'builtin:evolution',
    label: '进化反馈',
    icon: 'RocketOutlined',
    category: 'ai',
    description: '触发系统进化学习',
    subBlocks: [
      {
        id: 'feedback',
        title: '反馈内容',
        type: 'textarea',
        required: true,
        placeholder: '对当前任务的反馈',
      },
      {
        id: 'rating',
        title: '评分',
        type: 'slider',
        min: 0,
        max: 1,
        defaultValue: 0.5,
        description: '0=差, 1=好',
      },
      {
        id: 'action',
        title: '进化动作',
        type: 'select',
        options: [
          { label: '记录经验', value: 'record' },
          { label: '结晶模式', value: 'crystallize' },
          { label: '调整权重', value: 'adjust' },
        ],
        defaultValue: 'record',
      },
    ],
    defaultData: {
      rating: 0.5,
      action: 'record',
    },
  },
]

// 获取节点 UI 定义
export function getBuiltinNodeUIDefinition(type: string): NodeUIDefinition | undefined {
  return builtinNodeUIDefinitions.find(def => def.type === type)
}

// 获取所有内置节点类型
export function getBuiltinNodeTypes(): string[] {
  return builtinNodeUIDefinitions.map(def => def.type)
}

// 按分类获取节点定义
export function getBuiltinNodesByCategory(category: string): NodeUIDefinition[] {
  return builtinNodeUIDefinitions.filter(def => def.category === category)
}

// 获取所有分类
export function getBuiltinCategories(): string[] {
  const categories = new Set(builtinNodeUIDefinitions.map(def => def.category))
  return Array.from(categories).sort()
}