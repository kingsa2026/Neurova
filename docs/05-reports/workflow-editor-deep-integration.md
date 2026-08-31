# 工作流编辑器深度集成方案

> 核心理念：工作流编辑器不是"又一个模块"，而是 Neurova 全部能力的可视化投射层。

---

## 一、为什么"从零搭建"是错误的

传统做法：建一套独立的节点类型系统 → 独立的执行引擎 → 独立的变量系统 → 独立的存储

问题：
- 节点类型和 ToolEngine/SkillRegistry **重复定义**
- 执行逻辑和 PlanOrchestrator/SkillChainExecutor **重复实现**
- 变量系统和 MemoryManager/ContextPool **各说各话**
- 维护成本翻倍，一致性无法保证

## 二、深度集成：三面镜子架构

```
┌─────────────────────────────────────────────────────────────┐
│                    工作流编辑器 (Vue 前端)                      │
│                                                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐   │
│  │ 节点面板  │  │  画布     │  │ 配置面板  │  │ 执行面板  │   │
│  │(自动发现) │  │(VueFlow) │  │(动态渲染) │  │(实时追踪) │   │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘   │
│       │              │              │              │          │
│  ┌────▼──────────────▼──────────────▼──────────────▼────┐   │
│  │              Block Registry (UI 投射层)                │   │
│  │                                                       │   │
│  │  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐   │   │
│  │  │ToolEngine│ │  Skill  │ │MCP Tools│ │ 内置节点 │   │   │
│  │  │ 工具→节点 │ │ 技能→节点│ │ MCP→节点 │ │ 手动注册 │   │   │
│  │  └─────────┘ └─────────┘ └─────────┘ └─────────┘   │   │
│  └──────────────────────────────────────────────────────┘   │
│                              │                               │
│  ┌───────────────────────────▼───────────────────────────┐   │
│  │              变量系统 (Neurova 上下文桥接)               │   │
│  │                                                        │   │
│  │  $memory    → MemoryManager.search()                  │   │
│  │  $context   → ContextPool.get()                       │   │
│  │  $emotion   → EmotionModule.current()                 │   │
│  │  $crystal   → PatternCrystallizer.retrieve()          │   │
│  │  $node.xxx  → 上游节点输出                             │   │
│  └────────────────────────────────────────────────────────┘   │
│                              │                               │
│  ┌───────────────────────────▼───────────────────────────┐   │
│  │              执行引擎 (委托现有系统)                     │   │
│  │                                                        │   │
│  │  DAG 编排    → PlanOrchestrator                       │   │
│  │  技能链执行  → SkillChainExecutor                      │   │
│  │  工具执行    → ToolEngine                              │   │
│  │  LLM 调用   → Agent.chat() / MultiModelLLMClient      │   │
│  │  人工审批    → ChannelManager (飞书/钉钉/微信/邮件)     │   │
│  └────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

## 三、关键设计：节点 = 注册表的 UI 视图

### 3.1 自动发现机制

```typescript
// neuUI/src/workflow/registry.ts

// 启动时从后端获取所有已注册的工具/技能
async function discoverNodes(): Promise<BlockTypeDefinition[]> {
  const [tools, skills, mcp] = await Promise.all([
    toolEngineAPI.listTools(),    // ToolEngine 所有已注册工具
    skillRegistryAPI.list(),       // SkillRegistry 所有技能
    mcpAPI.listTools(),           // MCP 动态工具
  ])
  
  return [
    ...tools.map(t => toolToBlock(t)),   // 工具 → 工作流节点
    ...skills.map(s => skillToBlock(s)), // 技能 → 工作流节点
    ...mcp.map(m => mcpToBlock(m)),      // MCP → 工作流节点
    ...builtinBlocks(),                   // 内置节点（条件/循环/合并等）
  ]
}

// 工具 → 节点映射
function toolToBlock(tool: ToolDef): BlockTypeDefinition {
  return {
    type: `tool:${tool.name}`,
    label: tool.display_name || tool.name,
    icon: tool.icon || '🔧',
    category: 'tools',
    description: tool.description,
    // 参数 → SubBlockConfig 自动转换
    subBlocks: tool.parameters?.map(p => paramToSubBlock(p)) ?? [],
    inputs: [{ id: 'input', label: '输入', required: false }],
    outputs: [{ id: 'output', label: '输出' }],
  }
}

// 参数 → 表单字段自动映射
function paramToSubBlock(param: ToolParam): SubBlockConfig {
  const typeMap: Record<string, SubBlockConfig['type']> = {
    'string': 'input',
    'number': 'slider',
    'boolean': 'switch',
    'enum': 'select',
    'object': 'json',
    'array': 'json',
  }
  return {
    id: param.name,
    title: param.description || param.name,
    type: typeMap[param.type] ?? 'input',
    placeholder: param.description,
    options: param.enum?.map(v => ({ label: v, value: v })),
    required: param.required,
  }
}
```

### 3.2 效果

- 注册一个新 Tool → 自动变成工作流节点，**零前端代码**
- 注册一个新 Skill → 自动变成工作流节点
- 连接一个 MCP Server → 所有 MCP 工具自动变成工作流节点
- 节点面板 = 后端能力的实时镜像

## 四、执行：委托而非重写

### 4.1 工作流定义标准化

```typescript
// 工作流序列化格式（前后端通用）
interface WorkflowDefinition {
  id: string
  name: string
  nodes: WorkflowNode[]
  edges: WorkflowEdge[]
  variables?: Record<string, any>  // 全局变量
}

interface WorkflowNode {
  id: string
  type: string           // "tool:web_search" | "skill:article" | "builtin:condition"
  position: { x: number; y: number }
  config: Record<string, any>  // SubBlockConfig 的值
}

interface WorkflowEdge {
  id: string
  source: string
  target: string
  sourceHandle?: string  // 条件分支: "true" | "false"
  condition?: string     // 条件表达式
}
```

### 4.2 后端执行器（复用现有系统）

```python
# neurova/execution_engine/workflow_executor.py (增强现有 WorkflowEngine)

class WorkflowExecutor:
    """工作流执行器 — 委托给现有系统"""
    
    def __init__(self):
        self.plan_orchestrator = get_plan_orchestrator()
        self.tool_engine = get_tool_engine()
        self.skill_chain = SkillChainExecutor()
        self.channel_manager = get_channel_manager()
    
    async def execute(self, workflow: WorkflowDefinition, context: dict) -> ExecutionResult:
        # 1. DAG 拓扑排序（复用 PlanOrchestrator）
        sorted_nodes = self._topological_sort(workflow.nodes, workflow.edges)
        
        # 2. 变量解析器
        resolver = VariableResolver(workflow, context)
        
        # 3. 按拓扑顺序执行
        results: dict[str, Any] = {}
        for node in sorted_nodes:
            # 解析节点输入变量
            resolved_config = resolver.resolve(node.config, results)
            
            # 按节点类型委托
            result = await self._execute_node(node, resolved_config, results)
            results[node.id] = result
            
            # 条件分支判断
            if node.type == 'builtin:condition':
                branch = self._evaluate_condition(result, node.config)
                # 跳过不需要执行的分支节点
        
        return ExecutionResult(results=results, status='completed')
    
    async def _execute_node(self, node, config, context):
        """按节点类型委托给不同系统"""
        
        if node.type.startswith('tool:'):
            # 委托给 ToolEngine
            tool_name = node.type.split(':')[1]
            return await self.tool_engine.execute(tool_name, config)
        
        elif node.type.startswith('skill:'):
            # 委托给 SkillChainExecutor
            skill_name = node.type.split(':')[1]
            return await self.skill_chain.execute_skill(skill_name, config)
        
        elif node.type.startswith('mcp:'):
            # 委托给 MCPToolClient
            _, server, tool = node.type.split(':')
            return await mcp_client.execute_tool(server, tool, config)
        
        elif node.type == 'builtin:llm':
            # 委托给 Agent LLM
            return await self._call_llm(config, context)
        
        elif node.type == 'builtin:review':
            # 委托给 ChannelManager（人工审批）
            return await self._human_review(config, context)
        
        elif node.type == 'builtin:memory':
            # 委托给 MemoryManager
            return await self._memory_operation(config, context)
```

### 4.3 变量解析器（桥接 Neurova 上下文）

```python
class VariableResolver:
    """变量解析器 — 桥接工作流和 Neurova 记忆/上下文系统"""
    
    def __init__(self, workflow, context):
        self.workflow = workflow
        self.context = context
        self.memory_manager = get_memory_manager()
        self.context_pool = get_context_pool()
    
    def resolve(self, config: dict, node_results: dict) -> dict:
        """解析配置中的所有变量引用"""
        resolved = {}
        for key, value in config.items():
            resolved[key] = self._resolve_value(value, node_results)
        return resolved
    
    def _resolve_value(self, value, node_results):
        if not isinstance(str, value):
            return value
        
        # $node.xxx.output → 上游节点输出
        if value.startswith('$node.'):
            parts = value.split('.')
            node_id = parts[1]
            field = parts[2] if len(parts) > 2 else 'output'
            return node_results.get(node_id, {}).get(field)
        
        # $memory.query → 记忆检索
        if value.startswith('$memory.'):
            query = value[len('$memory.'):]
            return self.memory_manager.search(query)
        
        # $context → 当前上下文
        if value == '$context':
            return self.context_pool.get_context()
        
        # $emotion → 当前情感状态
        if value == '$emotion':
            return self.context.get('emotion', {})
        
        # $input → 工作流输入
        if value == '$input':
            return self.context.get('input', {})
        
        # 模板变量 {{variable}}
        return self._resolve_template(value, node_results)
```

## 五、前端架构

### 5.1 目录结构

```
neuUI/src/workflow/
├── registry.ts              # Block 注册表（自动发现 + 手动注册）
├── types.ts                 # 类型定义（BlockTypeDefinition, SubBlockConfig, etc.）
├── validation.ts            # 工作流验证引擎
├── serializer.ts            # 序列化/反序列化
├── variable-resolver.ts     # 前端变量解析（预览用）
├── blocks/
│   ├── builtin.ts           # 内置节点（条件/循环/合并/输入/输出）
│   ├── index.ts             # 注册表入口
│   └── adapters.ts          # Tool/Skill/MCP → Block 适配器
├── components/
│   ├── WorkflowCanvas.vue   # 画布主组件
│   ├── NodePalette.vue      # 左侧节点面板
│   ├── NodeInspector.vue    # 右侧配置面板
│   ├── SubBlockRenderer.vue # 通用参数渲染器
│   ├── ModelSelector.vue    # LLM 选择器
│   ├── ExecutionPanel.vue   # 执行日志面板
│   ├── ValidationPanel.vue  # 验证错误面板
│   └── nodes/
│       ├── BuiltinNode.vue  # 内置节点渲染
│       ├── ToolNode.vue     # 工具节点渲染
│       └── SkillNode.vue    # 技能节点渲染
└── composables/
    ├── useWorkflowStore.ts  # Pinia store（UI 状态）
    ├── useWorkflowAPI.ts    # API 调用（TanStack Query）
    └── useExecution.ts      # 执行状态管理
```

### 5.2 SubBlockRenderer — 通用参数渲染器

```vue
<!-- neuUI/src/workflow/components/SubBlockRenderer.vue -->
<template>
  <template v-for="block in visibleSubBlocks" :key="block.id">
    <a-form-item :label="block.title" :required="block.required">
      <!-- 根据 type 自动选择组件 -->
      <a-input v-if="block.type === 'input'" v-model:value="values[block.id]" :placeholder="block.placeholder" />
      <a-textarea v-else-if="block.type === 'textarea'" v-model:value="values[block.id]" :rows="3" />
      <a-select v-else-if="block.type === 'select'" v-model:value="values[block.id]" :options="block.options" />
      <a-slider v-else-if="block.type === 'slider'" v-model:value="values[block.id]" :min="block.min" :max="block.max" />
      <a-switch v-else-if="block.type === 'switch'" v-model:checked="values[block.id]" />
      <CodeEditor v-else-if="block.type === 'code'" v-model="values[block.id]" :language="block.language" />
      <JsonEditor v-else-if="block.type === 'json'" v-model="values[block.id]" />
      <ModelSelector v-else-if="block.type === 'model-selector'" v-model:provider="values[block.id + '_provider']" v-model:model="values[block.id]" :capability="block.providerCapability" />
    </a-form-item>
  </template>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { SubBlockConfig } from '../types'

const props = defineProps<{
  subBlocks: SubBlockConfig[]
  values: Record<string, any>
}>()

// 条件可见性过滤
const visibleSubBlocks = computed(() => {
  return props.subBlocks.filter(block => {
    if (!block.condition) return true
    const { field, operator, value } = block.condition
    const fieldValue = props.values[field]
    switch (operator) {
      case 'eq': return fieldValue === value
      case 'neq': return fieldValue !== value
      case 'in': return Array.isArray(value) && value.includes(fieldValue)
      default: return true
    }
  })
})
</script>
```

### 5.3 自动化节点面板

```vue
<!-- neuUI/src/workflow/components/NodePalette.vue -->
<template>
  <div class="node-palette">
    <a-input-search v-model:value="searchQuery" placeholder="搜索节点..." size="small" />
    
    <div v-for="category in filteredCategories" :key="category.key" class="category-group">
      <div class="category-header" @click="category.open = !category.open">
        <span>{{ category.icon }} {{ category.label }}</span>
        <span class="count">{{ category.items.length }}</span>
      </div>
      <div v-show="category.open" class="node-list">
        <div v-for="node in category.items" :key="node.type" 
             class="node-item" draggable="true"
             @dragstart="onDragStart($event, node)">
          <span class="node-icon">{{ node.icon }}</span>
          <span class="node-label">{{ node.label }}</span>
          <a-tooltip v-if="node.source === 'tool'" title="来自 ToolEngine">
            <span class="source-badge tool">T</span>
          </a-tooltip>
          <a-tooltip v-else-if="node.source === 'skill'" title="来自 SkillRegistry">
            <span class="source-badge skill">S</span>
          </a-tooltip>
          <a-tooltip v-else-if="node.source === 'mcp'" title="来自 MCP">
            <span class="source-badge mcp">M</span>
          </a-tooltip>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useQuery } from '@tanstack/vue-query'
import { discoverNodes, groupByCategory } from '../registry'

// 自动从后端发现所有可用节点
const { data: nodes } = useQuery({
  queryKey: ['workflow-nodes'],
  queryFn: discoverNodes,
  staleTime: 60_000,  // 1分钟缓存
})

const categories = computed(() => groupByCategory(nodes.value ?? []))
</script>
```

## 六、实施计划（3 个阶段，每阶段可独立交付）

### Phase 1: 基础画布 + Block Registry（5-7 天）

**目标**: 替换瘫痪的 WorkflowPage.vue，实现可用的工作流编辑器

| 任务 | 天数 | 产出 |
|------|------|------|
| 创建 `workflow/types.ts` 类型定义 | 0.5 | SubBlockConfig, BlockTypeDefinition, WorkflowDefinition |
| 创建 `workflow/registry.ts` 注册表 | 1 | 自动发现 + 手动注册 + 分类聚合 |
| 创建 `blocks/builtin.ts` 内置节点 | 1 | 条件/循环/合并/输入/输出/LLM/记忆 等 15 个节点 |
| 创建 `SubBlockRenderer.vue` | 1 | 通用参数渲染器（替代 160 行 v-if 链） |
| 重写 `WorkflowPage.vue` | 2 | 使用新组件重构画布 + 面板 + 配置 |
| 创建 `validation.ts` | 0.5 | 工作流验证引擎 |
| 后端 API 适配 | 1 | 适配现有 workflows_api.py |

**交付物**: 可用的工作流编辑器，支持 15+ 内置节点类型，拖拽连线，配置保存

### Phase 2: 深度集成（5-7 天）

**目标**: 节点面板自动反映后端能力

| 任务 | 天数 | 产出 |
|------|------|------|
| 后端: ToolEngine → 节点发现 API | 1 | GET /workflow/nodes/discover |
| 后端: SkillRegistry → 节点发现 API | 0.5 | 合并到 discover |
| 后端: MCP → 节点发现 API | 0.5 | 合并到 discover |
| 前端: 适配器 (tool/skill/mcp → Block) | 1 | 自动映射参数 → SubBlockConfig |
| 后端: 工作流执行器增强 | 2 | 委托给 ToolEngine/PlanOrchestrator |
| 后端: 变量解析器 | 1 | $memory/$context/$emotion/$node 引用 |
| 前端: ModelSelector 组件 | 0.5 | 提取 LLM 选择器 |

**交付物**: 注册新 Tool 自动变成工作流节点，支持 $memory/$context 变量引用

### Phase 3: 高级功能（5-7 天）

**目标**: Human-in-the-loop + 写作模板 + 执行监控

| 任务 | 天数 | 产出 |
|------|------|------|
| Human-in-the-loop 节点 | 2 | 审批节点（通过 ChannelManager 推送到飞书/钉钉） |
| 写作工作流模板 | 1.5 | 文章/报告/技术文档 预定义模板 |
| 执行日志面板 | 1.5 | 实时追踪每个节点的输入/输出/状态 |
| 子工作流支持 | 1.5 | 宏节点（引用其他工作流） |
| AI 自动生成工作流增强 | 0.5 | 对接后端 generate API |

**交付物**: 完整的深度集成工作流系统

## 七、与现有模块的集成清单

| Neurova 模块 | 集成方式 | 工作流节点类型 |
|-------------|---------|--------------|
| ToolEngine | 自动发现 → 节点注册 | `tool:{name}` |
| SkillRegistry | 自动发现 → 节点注册 | `skill:{name}` |
| MCPToolClient | 自动发现 → 节点注册 | `mcp:{server}:{tool}` |
| MemoryManager | 变量引用 $memory | `builtin:memory-load/save` |
| ContextPool | 变量引用 $context | 自动注入 |
| EmotionModule | 变量引用 $emotion | 自动注入 |
| PlanOrchestrator | DAG 拓扑排序 + 执行 | 后端执行器 |
| SkillChainExecutor | 技能链执行 | 后端执行器 |
| ChannelManager | 人工审批通知 | `builtin:review` |
| Agent.chat() | LLM 调用 | `builtin:llm` |
| PatternCrystallizer | 结晶经验注入 | 自动注入 |
| LLMRouter | 多模型路由 | `builtin:llm` (自动选择模型) |
