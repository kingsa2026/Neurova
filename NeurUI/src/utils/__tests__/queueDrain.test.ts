/**
 * 审计修复①③⑯：队列续发 runner（utils/queueDrain）。
 *
 * - ① P0 续发死锁：ChatPage 旧实现 drain 设置 _draining=true 后 await
 *   sendMessage，sendMessage finally 的递归 drain 被守卫吞掉，外层复位
 *   退出 → 排队 ≥2 条只自动发 1 条。修复=runner 循环续发 + 重入调用
 *   降级为 no-op（外层循环驱动）。
 * - ⑯ paused+空闲时显式 send-now 静默无动作 → force 语义（只放行入口，
 *   续发仍尊重 paused）。
 * 本 runner 把该逻辑从 ChatPage 抽为可测纯依赖注入模块。
 */
import { describe, expect, it, vi } from 'vitest'
import { createQueueDrainer, type QueueDrainDeps } from '../queueDrain'

function makeDeps(overrides: Partial<QueueDrainDeps> = {}) {
  const sent: string[] = []
  const failed: Array<{ id: string; error?: string }> = []
  const items: Array<{ id: string; text: string; status: 'pending' | 'sending' | 'failed' }> = [
    { id: 'a', text: '第一条', status: 'pending' },
    { id: 'b', text: '第二条', status: 'pending' },
    { id: 'c', text: '第三条', status: 'pending' },
  ]
  const deps: QueueDrainDeps = {
    isPaused: () => false,
    takeNext: () => {
      const it = items.find((i) => i.status === 'pending')
      return it ? { id: it.id, text: it.text } : undefined
    },
    markSending: (id: string) => {
      const it = items.find((i) => i.id === id)
      if (!it || it.status !== 'pending') return false
      it.status = 'sending'
      return true
    },
    markSent: (id: string) => {
      sent.push(id)
      const idx = items.findIndex((i) => i.id === id)
      if (idx >= 0) items.splice(idx, 1)
    },
    markFailed: (id: string, error?: string) => {
      failed.push({ id, error })
      const it = items.find((i) => i.id === id)
      if (it) it.status = 'failed'
    },
    send: vi.fn(async () => true),
    ...overrides,
  }
  return { deps, sent, failed, items }
}

describe('queueDrain（审计① P0 续发死锁）', () => {
  it('递归重入（sendMessage finally 形态）被吞后，外层循环仍续发全部排队项', async () => {
    const { deps, sent } = makeDeps()
    const drainer = createQueueDrainer(deps)
    // 模拟生产形态：send 内部（sendMessage finally）再次调 drain
    const sendWithRecursion = async (text: string): Promise<boolean> => {
      await drainer.drain()
      return true
    }
    deps.send = sendWithRecursion

    await drainer.drain()
    expect(sent).toEqual(['a', 'b', 'c'])
  })

  it('send 返回 false → markFailed（不误标成功出队）', async () => {
    const { deps, failed } = makeDeps({
      send: vi.fn(async () => false),
    })
    const drainer = createQueueDrainer(deps)
    await drainer.drain()
    expect(failed.length).toBe(3)
  })

  it('send 抛错 → markFailed 携带错误并继续下一条', async () => {
    const { deps, failed, sent } = makeDeps({
      send: vi.fn(async (text: string) => {
        if (text === '第一条') throw new Error('boom')
        return true
      }),
    })
    const drainer = createQueueDrainer(deps)
    await drainer.drain()
    expect(failed[0]).toEqual({ id: 'a', error: 'boom' })
    expect(sent).toEqual(['b', 'c'])
  })

  it('drain 进行中重入调用为 no-op', async () => {
    const { deps, sent } = makeDeps()
    const drainer = createQueueDrainer(deps)
    let release!: () => void
    const gate = new Promise<void>((r) => (release = r))
    deps.send = vi.fn(async () => {
      await gate
      return true
    })
    const p1 = drainer.drain()
    const p2 = drainer.drain() // 重入
    expect(drainer.isDraining()).toBe(true)
    release()
    await Promise.all([p1, p2])
    expect(sent).toEqual(['a', 'b', 'c'])
  })

  it('markSending 恒失败（病态场景）→ 防死循环护栏退出', async () => {
    const { deps, sent } = makeDeps()
    // 出队式夹具（takeNext 不重发同一项，与真实 store next/markSending 同源
    // 语义一致）：markSending 恒 false → 每项跳过 → 队列耗尽退出
    const queue = ['a', 'b', 'c']
    deps.takeNext = () => {
      const id = queue.shift()
      return id ? { id, text: id } : undefined
    }
    deps.markSending = () => false
    const drainer = createQueueDrainer(deps)
    await drainer.drain()
    expect(sent).toEqual([])
  })

  it('markSending 竞争失败（项被移除）→ 跳过该条继续发后续', async () => {
    const { deps, sent } = makeDeps()
    // 真实竞争：takeNext 返回 a 后、markSending 前，a 被用户移除
    //（takeNext 出队式不重发 + markSending 对 a 返回 false）
    const queue = ['a', 'b', 'c']
    deps.takeNext = () => {
      const id = queue.shift()
      return id ? { id, text: id } : undefined
    }
    deps.markSending = (id: string) => {
      if (id === 'a') return false
      return true
    }
    const drainer = createQueueDrainer(deps)
    await drainer.drain()
    expect(sent).toEqual(['b', 'c'])
  })
})

describe('queueDrain paused 语义（审计⑯）', () => {
  it('paused 时默认 drain 不发送（自动续发尊重暂停）', async () => {
    const { deps, sent } = makeDeps({ isPaused: () => true })
    const drainer = createQueueDrainer(deps)
    await drainer.drain()
    expect(sent).toEqual([])
  })

  it('paused 时 force 入口只发送一条（显式「立即」），续发仍尊重 paused', async () => {
    const { deps, sent } = makeDeps({ isPaused: () => true })
    const drainer = createQueueDrainer(deps)
    await drainer.drain(true)
    expect(sent).toEqual(['a'])
  })

  it('未 paused 时 force 与普通 drain 等价（排空）', async () => {
    const { deps, sent } = makeDeps()
    const drainer = createQueueDrainer(deps)
    await drainer.drain(true)
    expect(sent).toEqual(['a', 'b', 'c'])
  })
})
