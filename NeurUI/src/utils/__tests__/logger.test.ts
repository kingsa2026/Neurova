/**
 * 阶段6 RED: 验证统一前端日志库
 *
 * 测试内容：
 * 1. logger.debug/info/warn/error 方法存在
 * 2. 日志级别过滤（level=info 时，debug 不输出）
 * 3. 日志收集（getLogs() 返回已记录的日志数组）
 * 4. 日志清空（clear() 清空日志）
 * 5. 与 bus 集成（error 级别触发 bus.emit('notification:show', ...))
 * 6. 保留最近 100 条日志
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import logger from '../logger'
import bus from '@/bus'

describe('logger - 方法存在性', () => {
  it('应暴露 debug 方法', () => {
    expect(typeof logger.debug).toBe('function')
  })

  it('应暴露 info 方法', () => {
    expect(typeof logger.info).toBe('function')
  })

  it('应暴露 warn 方法', () => {
    expect(typeof logger.warn).toBe('function')
  })

  it('应暴露 error 方法', () => {
    expect(typeof logger.error).toBe('function')
  })

  it('应暴露 setLevel 方法', () => {
    expect(typeof logger.setLevel).toBe('function')
  })

  it('应暴露 getLogs 方法', () => {
    expect(typeof logger.getLogs).toBe('function')
  })

  it('应暴露 clear 方法', () => {
    expect(typeof logger.clear).toBe('function')
  })
})

describe('logger - 日志收集', () => {
  beforeEach(() => {
    logger.clear()
    logger.setLevel('debug')
    vi.spyOn(console, 'debug').mockImplementation(() => {})
    vi.spyOn(console, 'info').mockImplementation(() => {})
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    vi.spyOn(console, 'error').mockImplementation(() => {})
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('getLogs 初始应为空数组', () => {
    expect(logger.getLogs()).toEqual([])
  })

  it('调用 debug 后应在 getLogs 中出现', () => {
    logger.debug('调试信息')
    const logs = logger.getLogs()
    expect(logs).toHaveLength(1)
    expect(logs[0]).toMatchObject({
      level: 'debug',
      message: '调试信息',
    })
    expect(typeof logs[0].timestamp).toBe('number')
  })

  it('调用 info 后应在 getLogs 中出现', () => {
    logger.info('信息')
    const logs = logger.getLogs()
    expect(logs).toHaveLength(1)
    expect(logs[0]).toMatchObject({ level: 'info', message: '信息' })
  })

  it('调用 warn 后应在 getLogs 中出现', () => {
    logger.warn('警告')
    const logs = logger.getLogs()
    expect(logs).toHaveLength(1)
    expect(logs[0]).toMatchObject({ level: 'warn', message: '警告' })
  })

  it('调用 error 后应在 getLogs 中出现', () => {
    logger.error('错误')
    const logs = logger.getLogs()
    expect(logs).toHaveLength(1)
    expect(logs[0]).toMatchObject({ level: 'error', message: '错误' })
  })

  it('应保留附加参数', () => {
    logger.info('带参数', { key: 'value' }, 42)
    const logs = logger.getLogs()
    expect(logs).toHaveLength(1)
    expect(logs[0].args).toEqual([{ key: 'value' }, 42])
  })
})

describe('logger - 日志级别过滤', () => {
  beforeEach(() => {
    logger.clear()
    vi.spyOn(console, 'debug').mockImplementation(() => {})
    vi.spyOn(console, 'info').mockImplementation(() => {})
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    vi.spyOn(console, 'error').mockImplementation(() => {})
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('level=info 时，debug 不应被记录', () => {
    logger.setLevel('info')
    logger.debug('不应记录')
    expect(logger.getLogs()).toHaveLength(0)
  })

  it('level=info 时，info/warn/error 应被记录', () => {
    logger.setLevel('info')
    logger.debug('不应记录')
    logger.info('应记录')
    logger.warn('应记录')
    logger.error('应记录')
    const logs = logger.getLogs()
    expect(logs).toHaveLength(3)
    expect(logs.map((l) => l.level)).toEqual(['info', 'warn', 'error'])
  })

  it('level=warn 时，debug/info 不应被记录', () => {
    logger.setLevel('warn')
    logger.debug('不应记录')
    logger.info('不应记录')
    logger.warn('应记录')
    logger.error('应记录')
    const logs = logger.getLogs()
    expect(logs).toHaveLength(2)
    expect(logs.map((l) => l.level)).toEqual(['warn', 'error'])
  })

  it('level=error 时，只有 error 应被记录', () => {
    logger.setLevel('error')
    logger.debug('不应记录')
    logger.info('不应记录')
    logger.warn('不应记录')
    logger.error('应记录')
    const logs = logger.getLogs()
    expect(logs).toHaveLength(1)
    expect(logs[0].level).toBe('error')
  })

  it('level=debug 时，所有级别都应被记录', () => {
    logger.setLevel('debug')
    logger.debug('d')
    logger.info('i')
    logger.warn('w')
    logger.error('e')
    expect(logger.getLogs()).toHaveLength(4)
  })
})

describe('logger - clear 清空日志', () => {
  beforeEach(() => {
    logger.clear()
    logger.setLevel('debug')
    vi.spyOn(console, 'info').mockImplementation(() => {})
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('clear 应清空所有已收集的日志', () => {
    logger.info('日志1')
    logger.info('日志2')
    expect(logger.getLogs()).toHaveLength(2)
    logger.clear()
    expect(logger.getLogs()).toEqual([])
  })
})

describe('logger - bus 集成', () => {
  beforeEach(() => {
    logger.clear()
    logger.setLevel('debug')
    vi.spyOn(console, 'error').mockImplementation(() => {})
    vi.spyOn(console, 'info').mockImplementation(() => {})
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    vi.spyOn(console, 'debug').mockImplementation(() => {})
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('调用 error 应触发 bus notification:show 事件 (type=error)', () => {
    const handler = vi.fn()
    bus.on('notification:show', handler)
    logger.error('出错了')
    expect(handler).toHaveBeenCalledWith({ type: 'error', message: '出错了' })
    bus.off('notification:show', handler)
  })

  it('调用 info 不应触发 bus notification:show 事件', () => {
    const handler = vi.fn()
    bus.on('notification:show', handler)
    logger.info('信息')
    expect(handler).not.toHaveBeenCalled()
    bus.off('notification:show', handler)
  })

  it('调用 debug 不应触发 bus notification:show 事件', () => {
    const handler = vi.fn()
    bus.on('notification:show', handler)
    logger.debug('调试')
    expect(handler).not.toHaveBeenCalled()
    bus.off('notification:show', handler)
  })

  it('调用 warn 不应触发 bus notification:show 事件', () => {
    const handler = vi.fn()
    bus.on('notification:show', handler)
    logger.warn('警告')
    expect(handler).not.toHaveBeenCalled()
    bus.off('notification:show', handler)
  })
})

describe('logger - 保留最近 100 条日志', () => {
  beforeEach(() => {
    logger.clear()
    logger.setLevel('debug')
    vi.spyOn(console, 'info').mockImplementation(() => {})
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('超过 100 条时应丢弃最旧的日志', () => {
    for (let i = 0; i < 105; i++) {
      logger.info(`日志${i}`)
    }
    const logs = logger.getLogs()
    expect(logs).toHaveLength(100)
    // 最旧的 5 条应被丢弃，第一条应为 "日志5"
    expect(logs[0].message).toBe('日志5')
    expect(logs[99].message).toBe('日志104')
  })
})

describe('logger - getLogs 返回副本', () => {
  beforeEach(() => {
    logger.clear()
    logger.setLevel('debug')
    vi.spyOn(console, 'info').mockImplementation(() => {})
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('getLogs 返回的数组修改不应影响内部状态', () => {
    logger.info('原始')
    const logs1 = logger.getLogs()
    logs1.push({ level: 'info', message: '篡改', timestamp: 0 })
    logs1[0].message = '篡改'

    const logs2 = logger.getLogs()
    expect(logs2).toHaveLength(1)
    expect(logs2[0].message).toBe('原始')
  })
})
