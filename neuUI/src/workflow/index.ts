/**
 * Neurflow 工作流模块导出
 */

// ==================== 类型定义 ====================
export * from './types'

// ==================== 工具函数 ====================
export * from './validation'
export * from './serializer'

// ==================== 组合式函数 ====================
export { useWorkflowStore } from './composables/useWorkflowStore'
export { useNeurflowAPI } from './composables/useWorkflowAPI'
export { useExecutionState } from './composables/useExecution'

// ==================== 组件 ====================
export { default as WorkflowPage } from './WorkflowPage.vue'
export { default as WorkflowCanvas } from './components/WorkflowCanvas.vue'
export { default as NodePalette } from './components/NodePalette.vue'
export { default as NodeInspector } from './components/NodeInspector.vue'
export { default as ExecutionPanel } from './components/ExecutionPanel.vue'
export { default as SubBlockRenderer } from './components/SubBlockRenderer.vue'
export { default as WorkflowNode } from './components/WorkflowNode.vue'
export { default as WorkflowEdge } from './components/WorkflowEdge.vue'
export { default as ModelSelector } from './components/ModelSelector.vue'
export { default as ValidationResult } from './components/ValidationResult.vue'

// 节点渲染器
export { default as BuiltinNode } from './components/nodes/BuiltinNode.vue'
export { default as ToolNode } from './components/nodes/ToolNode.vue'
export { default as SkillNode } from './components/nodes/SkillNode.vue'

// ==================== 节点定义 ====================
export { builtinNodeUIDefinitions, getBuiltinNodeUIDefinition, getBuiltinNodeTypes, getBuiltinNodesByCategory, getBuiltinCategories } from './blocks/builtin'
export { adaptToolToNode, adaptSkillToNode, adaptMCPToNode, adaptTools, adaptSkills, adaptMCPTools, adaptAllCapabilities, loadAndAdaptNodes, loadAndAdaptTools, loadAndAdaptSkills } from './blocks/adapters'

// ==================== 注册表 ====================
export { nodeRegistry, createNodeFactory, createEdgeFactory, registerDefaultNodes, loadNodesFromBackend, initializeNodeRegistry, getNodeIcon, getNodeColor, validateNodeDefinition, searchNodes, getNodesByCategory, getNodeCategories, getNodesBySource, getNodesByTag } from './registry'

// ==================== 常量 ====================
export const WORKFLOW_MODULE_VERSION = '1.0.0'

// ==================== 工厂函数 ====================

/**
 * 创建默认工作流定义
 */
export function createDefaultWorkflow() {
  return {
    id: `wf_${Date.now()}`,
    name: '新工作流',
    description: '',
    status: 'draft' as const,
    version: '1.0.0',
    nodes: [],
    edges: [],
    variables: [],
    createdAt: Date.now(),
    updatedAt: Date.now(),
  }
}

/**
 * 创建默认节点
 */
export function createDefaultNode(type: string, position: { x: number; y: number }) {
  return {
    id: `node_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
    type,
    label: type.split(':').pop() || type,
    position,
    data: {},
    inputs: [],
    outputs: [],
  }
}

/**
 * 创建默认边
 */
export function createDefaultEdge(source: string, target: string, sourceHandle?: string, targetHandle?: string) {
  return {
    id: `edge_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
    source,
    target,
    sourceHandle,
    targetHandle,
  }
}