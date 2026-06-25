/**
 * 阶段4 RED: 验证统一事件总线
 *
 * 测试 mitt 兼容接口：emit/on/off/clear + 类型安全
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mitt, bus } from '../index'
import type { Emitter } from '../index'

describe('Event Bus (mitt 兼容实现)', () => {
  let emitter: Emitter<{
    test: { value: number }
    login: { userId: string }
    void: void
  }>

  beforeEach(() => {
    emitter = mitt()
  })

  describe('on/emit', () => {
    it('应触发已注册的事件处理器', () => {
      const handler = vi.fn()
      emitter.on('test', handler)
      emitter.emit('test', { value: 42 })
      expect(handler).toHaveBeenCalledWith({ value: 42 })
    })

    it('应支持多个处理器', () => {
      const h1 = vi.fn()
      const h2 = vi.fn()
      emitter.on('test', h1)
      emitter.on('test', h2)
      emitter.emit('test', { value: 1 })
      expect(h1).toHaveBeenCalled()
      expect(h2).toHaveBeenCalled()
    })

    it('应支持 void 事件', () => {
      const handler = vi.fn()
      emitter.on('void', handler)
      emitter.emit('void', undefined)
      expect(handler).toHaveBeenCalledWith(undefined)
    })
  })

  describe('off', () => {
    it('应解绑指定处理器', () => {
      const handler = vi.fn()
      emitter.on('test', handler)
      emitter.off('test', handler)
      emitter.emit('test', { value: 1 })
      expect(handler).not.toHaveBeenCalled()
    })

    it('应解绑所有处理器（不传 handler）', () => {
      const h1 = vi.fn()
      const h2 = vi.fn()
      emitter.on('test', h1)
      emitter.on('test', h2)
      emitter.off('test')
      emitter.emit('test', { value: 1 })
      expect(h1).not.toHaveBeenCalled()
      expect(h2).not.toHaveBeenCalled()
    })
  })

  describe('通配符 *', () => {
    it('应触发所有事件', () => {
      const starHandler = vi.fn()
      emitter.on('*', starHandler)
      emitter.emit('test', { value: 1 })
      emitter.emit('login', { userId: 'u1' })
      expect(starHandler).toHaveBeenCalledTimes(2)
    })
  })

  describe('clear', () => {
    it('应清空所有事件处理器', () => {
      const handler = vi.fn()
      emitter.on('test', handler)
      emitter.clear()
      emitter.emit('test', { value: 1 })
      expect(handler).not.toHaveBeenCalled()
    })
  })
})

describe('全局 bus 单例', () => {
  it('应导出默认 bus 实例', () => {
    expect(bus).toBeDefined()
    expect(typeof bus.on).toBe('function')
    expect(typeof bus.emit).toBe('function')
    expect(typeof bus.off).toBe('function')
  })

  it('应支持 memory:created 事件', () => {
    const handler = vi.fn()
    bus.on('memory:created', handler)
    bus.emit('memory:created', { memoryId: 'mem_1', content: 'test' })
    expect(handler).toHaveBeenCalledWith({ memoryId: 'mem_1', content: 'test' })
    bus.off('memory:created', handler)
  })

  it('应支持 api:rate-limited 事件', () => {
    const handler = vi.fn()
    bus.on('api:rate-limited', handler)
    bus.emit('api:rate-limited', { requestId: 'r1', retryAfter: 60 })
    expect(handler).toHaveBeenCalledWith({ requestId: 'r1', retryAfter: 60 })
    bus.off('api:rate-limited', handler)
  })
})
