/**
 * DebugPanel 纯逻辑测试 — TDD 红灯先行。
 *
 * 范围：
 * 1. createDebugController() 工厂：管理 breakpoints/stepMode/variables
 * 2. toggleBreakpoint(nodeId)：加入/移出集合
 * 3. setMockOutput(nodeId, value)：设置 mock，clear=true 清空
 * 4. buildStepModePayload()：in/over/out → API payload
 * 5. requestResume()：构造请求体
 *
 * 不测 Vue 渲染（vue-tsc + vite 编译保证），只测纯状态逻辑。
 */
import { describe, expect, it, beforeEach } from 'vitest'
import {
  createDebugController,
  buildStepModePayload,
  type DebugController,
} from '../DebugPanel'

describe('createDebugController', () => {
  let ctrl: DebugController

  beforeEach(() => {
    ctrl = createDebugController('exec_test_1')
  })

  it('新建 controller 默认 breakpoints 为空', () => {
    expect(ctrl.breakpoints.value).toEqual(new Set())
  })

  it('新建 controller 默认 stepMode 为 null', () => {
    expect(ctrl.stepMode.value).toBeNull()
  })

  it('新建 controller 默认 variables 为空对象', () => {
    expect(ctrl.variables.value).toEqual({})
  })

  it('executionId 在 controller 上暴露', () => {
    expect(ctrl.executionId).toBe('exec_test_1')
  })
})

describe('toggleBreakpoint', () => {
  let ctrl: DebugController
  beforeEach(() => {
    ctrl = createDebugController('exec_2')
  })

  it('加入新节点', () => {
    ctrl.toggleBreakpoint('node_a')
    expect(ctrl.breakpoints.value.has('node_a')).toBe(true)
    expect(ctrl.breakpoints.value.size).toBe(1)
  })

  it('再次 toggle 移除已存在节点', () => {
    ctrl.toggleBreakpoint('node_a')
    ctrl.toggleBreakpoint('node_a')
    expect(ctrl.breakpoints.value.has('node_a')).toBe(false)
    expect(ctrl.breakpoints.value.size).toBe(0)
  })

  it('加入多个节点互不影响', () => {
    ctrl.toggleBreakpoint('node_a')
    ctrl.toggleBreakpoint('node_b')
    expect(ctrl.breakpoints.value.size).toBe(2)
    expect(ctrl.breakpoints.value.has('node_a')).toBe(true)
    expect(ctrl.breakpoints.value.has('node_b')).toBe(true)
  })
})

describe('setMockOutput', () => {
  let ctrl: DebugController
  beforeEach(() => {
    ctrl = createDebugController('exec_3')
  })

  it('设置 mock 值后记录存在', () => {
    ctrl.setMockOutput('node_a', { answer: 'mocked' })
    expect(ctrl.nodeMocks.value.get('node_a')).toEqual({ answer: 'mocked' })
  })

  it('覆盖旧值', () => {
    ctrl.setMockOutput('node_a', { v: 1 })
    ctrl.setMockOutput('node_a', { v: 2 })
    expect(ctrl.nodeMocks.value.get('node_a')).toEqual({ v: 2 })
  })

  it('clearMock 移除节点', () => {
    ctrl.setMockOutput('node_a', 42)
    ctrl.clearMock('node_a')
    expect(ctrl.nodeMocks.value.has('node_a')).toBe(false)
  })
})

describe('buildStepModePayload', () => {
  it('null 返回空对象', () => {
    expect(buildStepModePayload(null)).toEqual({})
  })

  it('"in" 返回 {step:"in"}', () => {
    expect(buildStepModePayload('in')).toEqual({ step: 'in' })
  })

  it('"over" 返回 {step:"over"}', () => {
    expect(buildStepModePayload('over')).toEqual({ step: 'over' })
  })

  it('"out" 返回 {step:"out"}', () => {
    expect(buildStepModePayload('out')).toEqual({ step: 'out' })
  })

  it('非法值回退到 {}', () => {
    // 故意传非法值，验证降级行为
    expect(buildStepModePayload('invalid' as unknown as null)).toEqual({})
  })
})