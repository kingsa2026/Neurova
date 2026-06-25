/**
 * 阶段5 RED: 验证统一 UI 提示库
 *
 * 测试内容：
 * 1. uiMessage.success/error/warning/info/loading 方法存在
 * 2. 统一配置（duration、top、maxCount）
 * 3. 去重功能（相同内容 1 秒内只显示一次，返回 false 表示被去重）
 * 4. 与 bus 集成（调用 success 时触发 bus.emit('notification:show', ...))
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'

// 使用 vi.hoisted 确保 mock 在 vi.mock 工厂提升后仍可访问
const messageMock = vi.hoisted(() => ({
  config: vi.fn(),
  success: vi.fn(),
  error: vi.fn(),
  warning: vi.fn(),
  info: vi.fn(),
  loading: vi.fn(),
}))

vi.mock('ant-design-vue', () => ({
  message: messageMock,
}))

// 在导入 uiMessage 之前先 mock，确保模块加载时调用 config 能被捕获
import { uiMessage, clearDedupeCache } from '../message'
import bus from '@/bus'

describe('uiMessage - 方法存在性', () => {
  it('应暴露 success 方法', () => {
    expect(typeof uiMessage.success).toBe('function')
  })

  it('应暴露 error 方法', () => {
    expect(typeof uiMessage.error).toBe('function')
  })

  it('应暴露 warning 方法', () => {
    expect(typeof uiMessage.warning).toBe('function')
  })

  it('应暴露 info 方法', () => {
    expect(typeof uiMessage.info).toBe('function')
  })

  it('应暴露 loading 方法', () => {
    expect(typeof uiMessage.loading).toBe('function')
  })
})

describe('uiMessage - 统一配置', () => {
  it('应在模块加载时调用 message.config 设置统一参数', () => {
    expect(messageMock.config).toHaveBeenCalled()
    const configArg = messageMock.config.mock.calls[0][0]
    expect(configArg).toMatchObject({
      duration: 3,
      top: '60px',
      maxCount: 3,
    })
  })
})

describe('uiMessage - 去重功能', () => {
  beforeEach(() => {
    clearDedupeCache()
    messageMock.success.mockClear()
    messageMock.error.mockClear()
    messageMock.warning.mockClear()
    messageMock.info.mockClear()
    messageMock.loading.mockClear()
    // 使用 vi.useFakeTimers 控制时间
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('首次调用 success 应返回 true 并显示消息', () => {
    const result = uiMessage.success('操作成功')
    expect(result).toBe(true)
    expect(messageMock.success).toHaveBeenCalledWith('操作成功', undefined)
  })

  it('1 秒内重复调用相同内容应返回 false 并跳过显示', () => {
    uiMessage.success('操作成功')
    const result = uiMessage.success('操作成功')
    expect(result).toBe(false)
    // message.success 只应被调用一次（第二次被去重）
    expect(messageMock.success).toHaveBeenCalledTimes(1)
  })

  it('超过 1 秒后重复调用相同内容应再次显示', () => {
    uiMessage.success('操作成功')
    vi.advanceTimersByTime(1001)
    const result = uiMessage.success('操作成功')
    expect(result).toBe(true)
    expect(messageMock.success).toHaveBeenCalledTimes(2)
  })

  it('不同内容应独立去重，互不影响', () => {
    uiMessage.success('消息A')
    const resultB = uiMessage.success('消息B')
    expect(resultB).toBe(true)
    expect(messageMock.success).toHaveBeenCalledTimes(2)
  })

  it('error 方法也应支持去重', () => {
    uiMessage.error('出错了')
    const result = uiMessage.error('出错了')
    expect(result).toBe(false)
    expect(messageMock.error).toHaveBeenCalledTimes(1)
  })

  it('warning 方法也应支持去重', () => {
    uiMessage.warning('警告')
    const result = uiMessage.warning('警告')
    expect(result).toBe(false)
    expect(messageMock.warning).toHaveBeenCalledTimes(1)
  })

  it('info 方法也应支持去重', () => {
    uiMessage.info('提示')
    const result = uiMessage.info('提示')
    expect(result).toBe(false)
    expect(messageMock.info).toHaveBeenCalledTimes(1)
  })

  it('loading 方法也应支持去重', () => {
    uiMessage.loading('加载中')
    const result = uiMessage.loading('加载中')
    expect(result).toBe(false)
    expect(messageMock.loading).toHaveBeenCalledTimes(1)
  })
})

describe('uiMessage - bus 集成', () => {
  beforeEach(() => {
    clearDedupeCache()
    messageMock.success.mockClear()
    messageMock.error.mockClear()
    messageMock.warning.mockClear()
    messageMock.info.mockClear()
    messageMock.loading.mockClear()
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('调用 success 应触发 bus notification:show 事件 (type=success)', () => {
    const handler = vi.fn()
    bus.on('notification:show', handler)
    uiMessage.success('操作成功')
    expect(handler).toHaveBeenCalledWith({ type: 'success', message: '操作成功' })
    bus.off('notification:show', handler)
  })

  it('调用 error 应触发 bus notification:show 事件 (type=error)', () => {
    const handler = vi.fn()
    bus.on('notification:show', handler)
    uiMessage.error('出错了')
    expect(handler).toHaveBeenCalledWith({ type: 'error', message: '出错了' })
    bus.off('notification:show', handler)
  })

  it('调用 warning 应触发 bus notification:show 事件 (type=warning)', () => {
    const handler = vi.fn()
    bus.on('notification:show', handler)
    uiMessage.warning('警告')
    expect(handler).toHaveBeenCalledWith({ type: 'warning', message: '警告' })
    bus.off('notification:show', handler)
  })

  it('调用 info 应触发 bus notification:show 事件 (type=info)', () => {
    const handler = vi.fn()
    bus.on('notification:show', handler)
    uiMessage.info('提示')
    expect(handler).toHaveBeenCalledWith({ type: 'info', message: '提示' })
    bus.off('notification:show', handler)
  })

  it('调用 loading 不应触发 bus notification:show 事件', () => {
    const handler = vi.fn()
    bus.on('notification:show', handler)
    uiMessage.loading('加载中')
    expect(handler).not.toHaveBeenCalled()
    bus.off('notification:show', handler)
  })

  it('被去重的消息不应触发 bus 事件', () => {
    const handler = vi.fn()
    bus.on('notification:show', handler)
    uiMessage.success('操作成功')
    uiMessage.success('操作成功') // 被去重
    expect(handler).toHaveBeenCalledTimes(1)
    bus.off('notification:show', handler)
  })
})

describe('uiMessage - duration 参数透传', () => {
  beforeEach(() => {
    clearDedupeCache()
    messageMock.success.mockClear()
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('应支持自定义 duration 参数', () => {
    uiMessage.success('自定义时长', 5)
    expect(messageMock.success).toHaveBeenCalledWith('自定义时长', 5)
  })
})
