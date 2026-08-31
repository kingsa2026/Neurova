# Sim Studio 前端借鉴分析 — 对 Neurova (neuUI) 的启发

> 生成日期: 2026-06-08

## 一、Sim Studio 前端架构概述

### 技术栈
| 维度 | Sim Studio | Neurova (neuUI) |
|------|-----------|----------------|
| 框架 | Next.js 15 (React) | Vue 3 + Vite |
| 状态管理 | Zustand (UI) + TanStack Query (server) | Pinia |
| 画布 | ReactFlow (`@xyflow/react`) | VueFlow (`@vue-flow/core`) |
| UI 库 | Shadcn/ui (Radix) + Tailwind | Ant Design Vue |
| 类型系统 | TypeScript 严格模式 | TypeScript |
| 构建 | Turborepo monorepo | Vite 单仓 |

**关键发现**: 两者都使用了基于 xyflow 的画布库（Sim=ReactFlow, Neurova=VueFlow），架构理念高度同源。

### 项目规模
- **Sim Studio**: Monorepo, apps/ + packages/, ~150+ 组件
- **Neurova**: 62 页面, 49 组件, 78 API 模块, 已有 50KB 的 `WorkflowPage.vue`

---

## 二、可借鉴的模式（按优先级排序）

### 优先级 1: SubBlockConfig 声明式参数系统 ⭐⭐⭐

**Sim Studio 的做法**:
每个 Block（节点）类型通过 `types.ts` 中的 `SubBlockConfig[]` 声明式定义其所有参数：

```typescript
// Sim Studio: blocks/types.ts
interface SubBlockConfig {
  id: string
  title: string
  type: 'short-input' | 'long-input' | 'dropdown' | 'switch' | 'slider' | 'code' | 'tool-input' | ...
  layout?: 'half' | 'full'
  placeholder?: string
  options?: { label: string; value: string }[]
  min?: number; max?: number; step?: number
  value?: any
  // 高级特性
  condition?: { field: string; value: any }  // 条件可见性
  dependsOn?: string[]                        // 依赖字段
  validation?: (value: any) => boolean        // 验证函数
  wandConfig?: { enabled: boolean; mode: string } // AI 辅助填充
}
```

**Neurova 现状**: `WorkflowPage.vue` 中节点配置通过大量 `v-if`/`v-else-if` 硬编码（约 160 行模板），每新增节点类型需手动添加模板+表单字段。

**借鉴方案**:
```typescript
// neuUI/src/workflow/block-registry.ts
interface SubBlockConfig {
  id: string
  title: string
  type: 'input' | 'textarea' | 'select' | 'slider' | 'switch' | 'code' | 'json' | 'model-selector'
  layout?: 'half' | 'full'
  placeholder?: string
  options?: { label: string; value: string }[] | (() => Promise<...>[])
  condition?: { field: string; operator: 'eq' | 'neq' | 'in'; value: any }
  dependsOn?: string[]
  validation?: (value: any, allValues: Record<string, any>) => string | null
  // Neurova 特有
  aiAssist?: boolean           // AI 帮忙填
  providerCapability?: string  // 关联 LLM 能力筛选
}

interface BlockTypeDefinition {
  type: string
  label: string
  icon: string
  color: string
  category: string
  description: string
  subBlocks: SubBlockConfig[]  // 声明式参数列表
  inputs: PortDef[]
  outputs: PortDef[]
}
```

**收益**: 新增节点类型只需注册一个 `BlockTypeDefinition`，无需改模板代码。配置表单自动渲染。

---

### 优先级 2: 块注册表 (Block Registry) ⭐⭐⭐

**Sim Studio 的做法**:
所有 Block 类型集中注册，画布渲染、序列化、执行器都从同一注册表查询：

```typescript
// blocks/index.ts
export const blockRegistry: Record<string, BlockTypeDefinition> = {
  'starter': StarterBlock,
  'agent': AgentBlock,
  'condition': ConditionBlock,
  // ...
}
```

**Neurova 现状**: 节点类型散落在 `nodeCategories` 数组（纯展示用）和 `openNodeConfig` 的 `v-if` 链（配置用）和 `WorkflowNode` 渲染函数（渲染用），三处不统一。

**借鉴方案**:
```typescript
// neuUI/src/workflow/registry.ts
import { blockRegistry } from './blocks'

// 注册所有节点类型
export function registerBlockType(def: BlockTypeDefinition) {
  blockRegistry[def.type] = def
}

// 各处统一查询
export function getBlockDef(type: string) { return blockRegistry[type] }
export function getBlockCategories() { /* 从注册表聚合 */ }
export function getBlockSubBlocks(type: string) { return blockRegistry[type]?.subBlocks ?? [] }
```

**收益**: 节点库面板、配置抽屉、序列化、后端执行全部从同一注册表查询，消除 3 处不一致。

---

### 优先级 3: 模型选择器组件提取 ⭐⭐

**Sim Studio 的做法**:
`ProviderModelSelector` 是独立组件，支持 provider + model 二级联动、能力过滤、状态缓存。

**Neurova 现状**: `WorkflowPage.vue` 中 LLM 选择器逻辑（`providerOpts`, `llmModelOpts`, `genModelOpts`, `onGenPChange`）约 80 行内联在页面中，重复 3 昵（LLM 对话、内容生成、未来扩展）。

**借鉴方案**:
```vue
<!-- neuUI/src/components/workflow/ModelSelector.vue -->
<template>
  <a-row :gutter="8">
    <a-col :span="12">
      <a-select v-model:value="providerId" :options="providerOpts" placeholder="服务商" @change="onProviderChange" />
    </a-col>
    <a-col :span="12">
      <a-select v-model:value="modelId" :options="modelOpts" placeholder="模型" show-search :disabled="!providerId" />
    </a-col>
  </a-row>
</template>
<script setup lang="ts">
// 封装 provider→model 二级联动、能力过滤、缓存
const props = defineProps<{ capability?: string; providerId?: string; modelId?: string }>()
const emit = defineEmits<{ 'update:providerId': [string]; 'update:modelId': [string] }>()
// 使用 Pinia store 或 TanStack Query 管理 provider 列表
</script>
```

**收益**: 消除 80 行重复逻辑，支持 4+ 处复用（LLM 对话、文本生成、图片生成、视频生成）。

---

### 优先级 4: 服务端状态管理层 (TanStack Query 模式) ⭐⭐

**Sim Studio 的做法**:
- Zustand: 纯 UI 状态（选中节点、画布缩放、侧栏展开）
- TanStack Query: 服务端状态（workflow CRUD、API 数据）自带缓存、乐观更新、重试

**Neurova 现状**: 所有状态混在 Pinia store 中，API 调用无统一缓存/重试策略。

**借鉴方案**:
```typescript
// 安装: npm i @tanstack/vue-query
// 引入: useQuery / useMutation 管理服务端状态

// neuUI/src/composables/useWorkflows.ts
import { useQuery, useMutation, useQueryClient } from '@tanstack/vue-query'

export function useWorkflows() {
  return useQuery({
    queryKey: ['workflows'],
    queryFn: () => workflowAPI.list(),
    staleTime: 30_000,  // 30秒内不重新请求
  })
}

export function useSaveWorkflow() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: SavePayload) => workflowAPI.update(data.id, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['workflows'] }),
    // 乐观更新
    onMutate: async (data) => { /* ... */ },
  })
}
```

**收益**: 自动缓存、去重、重试、乐观更新，减少 50%+ 的 loading/error 处理代码。

---

### 优先级 5: 工作流验证引擎 ⭐⭐

**Sim Studio 的做法**:
`lib/workflows/validation.ts` 独立验证模块，在保存/执行前校验：
- 未连接的输入端口
- 缺失必要配置
- 循环依赖
- 类型不匹配

**Neurova 现状**: 仅校验自连接和环检测 (`hasCycle`)，不检查配置完整性。

**借鉴方案**:
```typescript
// neuUI/src/workflow/validation.ts
interface ValidationResult {
  valid: boolean
  errors: ValidationError[]   // 阻断性错误
  warnings: ValidationWarning[] // 建议性警告
}

export function validateWorkflow(nodes: Node[], edges: Edge[]): ValidationResult {
  const errors: ValidationError[] = []
  const warnings: ValidationWarning[] = []

  // 1. 检查未连接的必需输入端口
  for (const node of nodes) {
    const def = getBlockDef(node.type)
    for (const input of def?.inputs ?? []) {
      if (input.required && !edges.some(e => e.target === node.id && e.targetHandle === input.id)) {
        errors.push({ nodeId: node.id, message: `缺少必需输入: ${input.label}` })
      }
    }
  }

  // 2. 检查配置完整性
  for (const node of nodes) {
    const def = getBlockDef(node.type)
    for (const sb of def?.subBlocks ?? []) {
      if (sb.required && !node.data?.[sb.id]) {
        errors.push({ nodeId: node.id, message: `未配置: ${sb.title}` })
      }
      // 条件验证
      if (sb.condition && !checkCondition(sb.condition, node.data)) continue
      const err = sb.validation?.(node.data?.[sb.id], node.data)
      if (err) errors.push({ nodeId: node.id, message: err })
    }
  }

  // 3. 环检测（已有）
  // ...

  return { valid: errors.length === 0, errors, warnings }
}
```

**收益**: 保存/执行前拦截配置错误，提升用户体验。

---

### 优先级 6: 人机交互节点 (Human-in-the-Loop) ⭐

**Sim Studio 的做法**:
专门的 `human-in-the-` 节点类型，支持：
- 表单收集节点（暂停执行等待用户填写）
- 审批节点（等待人工确认）
- 人工标注节点

**Neurova 现状**: `WorkflowPage.vue` 已有 `review`（人工审核）和 `task`（人工任务）节点，但无表单收集能力。

**借鉴方案**:
在已有节点基础上增加：
```typescript
// 新增: 表单收集节点
{
  type: 'form-collect',
  label: '表单收集',
  icon: '📋',
  category: 'quality',
  subBlocks: [
    { id: 'formSchema', title: '表单结构', type: 'json' },
    { id: 'timeout', title: '超时(秒)', type: 'slider', min: 60, max: 3600, value: 300 },
    { id: 'reminder', title: '提醒方式', type: 'select', options: [...] },
  ],
  inputs: [{ id: 'context', label: '上下文', required: false }],
  outputs: [{ id: 'formData', label: '用户填写数据' }],
}
```

---

### 优先级 7: 子工作流/组合节点 ⭐

**Sim Studio 的做法**:
支持将多个节点组合为一个"宏节点"，可在其他工作流中复用。

**Neurova 现状**: 工作流是扁平结构，无嵌套能力。

**借鉴方案**:
```typescript
// neuUI/src/workflow/blocks/macro.ts
interface MacroBlock extends BlockTypeDefinition {
  workflowId: string          // 引用的子工作流 ID
  inputMapping: Record<string, string>   // 外部输入 → 子工作流输入节点
  outputMapping: Record<string, string>  // 子工作流输出节点 → 外部输出
}
```

---

### 优先级 8: 流式预览面板 ⭐

**Sim Studio 的做法**:
执行工作流时右侧弹出实时日志面板，每个节点的输入/输出实时展示，支持 AI 流式 token 展示。

**Neurova 现状**: 无工作流执行日志 UI。

**借鉴方案**:
```vue
<!-- neuUI/src/components/workflow/ExecutionPanel.vue -->
<template>
  <a-drawer placement="right" width="480px" title="执行日志">
    <div v-for="log in executionLogs" :key="log.nodeId" class="log-entry">
      <div class="log-header">
        <NodeIcon :type="log.nodeType" />
        <span>{{ log.nodeName }}</span>
        <a-tag :color="statusColor(log.status)">{{ log.status }}</a-tag>
      </div>
      <div class="log-body" v-if="log.status !== 'pending'">
        <pre>{{ log.input }}</pre>
        <a-divider />
        <pre v-if="log.output">{{ log.output }}</pre>
        <span v-else-if="log.streaming" class="streaming-cursor">▌</span>
      </div>
    </div>
  </a-drawer>
</template>
```

---

## 三、实施路线图

### Phase 1: 基础架构（1-2 周）
1. **Block Registry**: 创建 `neuUI/src/workflow/registry.ts` + `blocks/types.ts`
2. **SubBlockConfig**: 定义声明式参数类型系统
3. **迁移现有节点**: 将 `nodeCategories` + `v-if` 配置链迁移到注册表

### Phase 2: 组件提取（1 周）
4. **ModelSelector 组件**: 从 `WorkflowPage.vue` 提取 LLM 选择器
5. **SubBlockRenderer**: 通用参数渲染器（替代 160 行 `v-if` 链）
6. **ValidationEngine**: 工作流验证引擎

### Phase 3: 状态管理升级（1 周）
7. **引入 TanStack Vue Query**: 管理 workflow/provider/agent API 状态
8. **Pinia store 瘦身**: 只保留 UI 状态

### Phase 4: 高级功能（2 周）
9. **Human-in-the-Loop 增强**: 表单收集节点
10. **执行日志面板**: 实时工作流执行监控
11. **子工作流**: 宏节点支持

---

## 四、不建议直接搬的模式

| Sim Studio 模式 | 原因 |
|----------------|------|
| React → Vue 直接移植 | 框架差异大，需重写 |
| Shadcn/ui 组件库 | 已有 Ant Design Vue，不换 |
| Next.js Server Actions | Vue 生态无需 SSR，Vite 足够 |
| Turborepo monorepo | Neurova 规模不需 monorepo |
| Zustand | Vue 用 Pinia 足够，引入 Zustand 增加复杂度 |

---

## 五、核心结论

**最大收益点**: SubBlockConfig + Block Registry + SubBlockRenderer 三件套。

这将 `WorkflowPage.vue` 中 ~200 行的硬编码配置模板变成零代码声明式定义。新增节点类型从"改 3 个地方"变成"注册一个配置对象"。

**已有基础**: `@vue-flow/core` 已安装，50KB 的 `WorkflowPage.vue` 已实现完整画布交互，节点分类体系已建立。升级路径清晰，无需推翻重来。
