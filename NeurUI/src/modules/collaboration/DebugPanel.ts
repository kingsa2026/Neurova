/**
 * DebugPanel 纯逻辑层 — 不含 Vue 渲染。
 *
 * 提供：
 * - createDebugController(executionId)：状态机（断点/mock/stepMode/variables）
 * - buildStepModePayload(mode)：构造 resume API 请求体
 *
 * Vue 组件（DebugPanel.vue）只负责渲染与用户交互。
 */
import { ref, type Ref } from 'vue'

export type StepMode = 'in' | 'over' | 'out' | null

export interface DebugController {
  executionId: string
  breakpoints: Ref<Set<string>>
  stepMode: Ref<StepMode>
  variables: Ref<Record<string, unknown>>
  nodeMocks: Ref<Map<string, unknown>>
  toggleBreakpoint: (nodeId: string) => void
  setStepMode: (mode: StepMode) => void
  setMockOutput: (nodeId: string, value: unknown) => void
  clearMock: (nodeId: string) => void
  setVariables: (vars: Record<string, unknown>) => void
}

export function createDebugController(executionId: string): DebugController {
  const breakpoints = ref<Set<string>>(new Set())
  const stepMode = ref<StepMode>(null)
  const variables = ref<Record<string, unknown>>({})
  const nodeMocks = ref<Map<string, unknown>>(new Map())

  function toggleBreakpoint(nodeId: string): void {
    const next = new Set(breakpoints.value)
    if (next.has(nodeId)) {
      next.delete(nodeId)
    } else {
      next.add(nodeId)
    }
    breakpoints.value = next
  }

  function setStepMode(mode: StepMode): void {
    stepMode.value = mode
  }

  function setMockOutput(nodeId: string, value: unknown): void {
    const next = new Map(nodeMocks.value)
    next.set(nodeId, value)
    nodeMocks.value = next
  }

  function clearMock(nodeId: string): void {
    if (!nodeMocks.value.has(nodeId)) return
    const next = new Map(nodeMocks.value)
    next.delete(nodeId)
    nodeMocks.value = next
  }

  function setVariables(vars: Record<string, unknown>): void {
    variables.value = { ...vars }
  }

  return {
    executionId,
    breakpoints,
    stepMode,
    variables,
    nodeMocks,
    toggleBreakpoint,
    setStepMode,
    setMockOutput,
    clearMock,
    setVariables,
  }
}

export function buildStepModePayload(mode: StepMode | string): Record<string, unknown> {
  if (mode === 'in' || mode === 'over' || mode === 'out') {
    return { step: mode }
  }
  return {}
}