/**
 * 增强族六条腿的调用必须带 `agent_id`（§6-433 前端半边）
 *
 * 后端那份装配点此前恒传 None ⇒ 动作一律打在默认 Agent 的库上；而记忆 id 是
 * 每库自增的 `mem_%06d`，两库同 id 是常态 ⇒ 在 kai 页面按 ↓ 可能改掉 default 的行。
 * 后端已接 `agent_id`，前端不传就等于没修。
 *
 * 判据取"发出去的请求长什么样"，不取注释：URL、请求体、`params.agent_id` 三处都核。
 * 反向一格：调用方没给作用域时**不硬塞空串**——`?agent_id=` 空值会把后端的
 * 「缺省回落 default」变成「按空串找 Agent」，两种语义不是一回事。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

const { get, post } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('@/api', () => ({
  request: { get, post },
  default: { get, post },
  api: { get, post },
}))

import * as memoryApi from '@/api/modules/memory'

const ENHANCE = '/memory-enhancement'

beforeEach(() => {
  vi.clearAllMocks()
  get.mockResolvedValue({ data: {} })
  post.mockResolvedValue({ data: {} })
})

/** 取"最后一次发出去的请求"。动词不同 ⇒ 配置位不同：`get(url, config)` 与
 *  `post(url, body, config)`。曾经用一个通用槽位读，把 GET 两条腿断言成了假绿。 */
function lastPost(): { url: string; body?: unknown; params?: Record<string, unknown> } {
  const args = post.mock.calls.at(-1) as [string, unknown, { params?: Record<string, unknown> }]
  return { url: String(args[0]), body: args[1], params: args[2]?.params }
}

function lastGet(): { url: string; params?: Record<string, unknown> } {
  const args = get.mock.calls.at(-1) as [string, { params?: Record<string, unknown> }]
  return { url: String(args[0]), params: args[1]?.params }
}

describe('增强族调用带作用域', () => {
  it('strengthen：按 id 寻址那一腿带上行自己的 agent_id', async () => {
    await memoryApi.strengthenMemory('mem_000006', 0.2, 'reason', 'kai')
    const call = lastPost()
    expect(call.url).toBe(`${ENHANCE}/mem_000006/strengthen`)
    expect(call.params).toEqual({ agent_id: 'kai' })
  })

  it('forget：同上', async () => {
    await memoryApi.forgetMemory('mem_000006', 'reason', 0.3, 'kai')
    expect(lastPost().params).toEqual({ agent_id: 'kai' })
  })

  it('batch / import：两条写入腿带作用域', async () => {
    await memoryApi.batchMemoryOperation(['mem_000001'], 'forget', {}, 'kai')
    expect(lastPost().params).toEqual({ agent_id: 'kai' })

    await memoryApi.importMemories([{ content: 'x' }], 'skip', 'kai')
    expect(lastPost().params).toEqual({ agent_id: 'kai' })
  })

  it('export / categories：两条读数腿也带作用域（GET 的配置位在第二个实参）', async () => {
    await memoryApi.exportMemories({ format: 'csv' }, 'kai')
    expect(lastGet().params).toMatchObject({ format: 'csv', agent_id: 'kai' })

    await memoryApi.getMemoryCategories('kai')
    expect(lastGet().params).toEqual({ agent_id: 'kai' })
  })

  it('反向：不给作用域就不塞空串（缺省回落 default 与按空串找 Agent 是两件事）', async () => {
    await memoryApi.strengthenMemory('mem_000001', 0.2, 'reason')
    expect(lastPost().params ?? {}).not.toHaveProperty('agent_id')

    await memoryApi.exportMemories({ format: 'json' })
    expect(lastGet().params ?? {}).not.toHaveProperty('agent_id')
    expect(lastGet().params).toMatchObject({ format: 'json' })
  })
})
