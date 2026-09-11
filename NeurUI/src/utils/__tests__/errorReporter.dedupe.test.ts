/**
 * errorReporter 去重 Map 封顶（P2-18 防回归）。
 *
 * 契约：
 * 1. capDedupeMap 超限按插入序淘汰最旧键，最新键保留（整体清空会连刚写入
 *    的键一起丢，30s 窗口内同错误会重复上报）；
 * 2. 集成侧：同一错误 30s 窗口内重复 capture 只入队一次（去重在封顶存在下
 *    仍然生效——淘汰最旧而非全清）。
 */
import { describe, it, expect, afterEach, vi } from 'vitest'
import { initErrorReporter, capDedupeMap } from '@/utils/errorReporter'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('capDedupeMap（P2-18）', () => {
  it('超限淘汰最旧键，保留最新键', () => {
    const map = new Map<string, number>()
    for (let i = 0; i < 205; i++) map.set(`k${i}`, i)

    capDedupeMap(map, 200)

    expect(map.size).toBe(200)
    // 最旧的 5 个（k0..k4）被淘汰
    expect(map.has('k0')).toBe(false)
    expect(map.has('k4')).toBe(false)
    // 其余键与最新键保留
    expect(map.has('k5')).toBe(true)
    expect(map.has('k204')).toBe(true)
  })

  it('未超限时不动任何键', () => {
    const map = new Map<string, number>([['a', 1], ['b', 2]])
    capDedupeMap(map, 200)
    expect(map.size).toBe(2)
  })
})

describe('errorReporter 去重（集成，fetch 挂起阻断 flush）', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it('同一错误窗口内重复 capture 只入队一次（封顶淘汰最旧而非全清）', () => {
    vi.useFakeTimers()
    // fetch 永不 resolve：queue 不被消费，queueLength 即入队计数
    vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})))
    const reporter = initErrorReporter({ force: true })
    try {
      reporter.capture('window', 'test-err', 'same message')
      reporter.capture('window', 'test-err', 'same message')
      reporter.capture('window', 'test-err', 'same message')
      expect(reporter.queueLength()).toBe(1)
    } finally {
      reporter.dispose()
    }
  })
})
