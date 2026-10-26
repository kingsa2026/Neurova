/**
 * 按 id 寻址的记忆路由必须带着「这一行属于哪个 Agent」——并披露这一行动不想动。
 *
 * 缺陷现场（2026-10-26 控制台读数）：`GET /api/v1/memory/merged_mem_000010_2` → 404。
 * 其中一条根因与租户无关，纯粹是寻址口径分家：列表函数 `getMemories(agentId, …)` 带
 * `agent_id`，而 `getMemory` / `updateMemory` / `deleteMemory` 三个按 id 的函数**不带**。
 * 后端 `get_memory_manager()` 缺 `agent_id` 即回落默认 Agent，于是页面选中非默认
 * Agent 时，表格里的每一行点「打开/编辑/删除」都打到另一个 Agent 的 manager 上。
 * 活体实证：`GET /memory/mem_000001` 404，`GET /memory/mem_000001?agent_id=kai` 200。
 *
 * 作用域取**行自带的 `record.agent_id`**（后端投影里本来就有这一列），不取页面当前选中项：
 * 行说它是谁的，就按谁的地址去要它。
 *
 * 第二半是 `rowIsActionable()`：列表面按 agent 全量口径放行（含他人用户域的行），
 * 详情/写面按三层隔离拒绝。所以「能不能动这一行」由后端逐条给的布尔 `owned` 说话，
 * 判定规则与闸门同一条（服务端 `isOwnedByRequestScope`）。前端只认这一处取法，
 * 不在页面里再猜一遍三元组。
 *
 * 用 namespace import 取符号：`rowIsActionable` 是本批新符号，若按具名 import 写，
 * 整档在加载期就 SyntaxError，把同档其它行为红一起吞掉。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  delete: vi.fn(),
}))

vi.mock('@/api', () => ({ default: apiMock, request: apiMock }))

import * as memoryApi from '@/api/modules/memory'

const ok = (data: unknown = {}) => Promise.resolve({ code: 0, data })

describe('记忆按 id 寻址带 agent_id', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    apiMock.get.mockImplementation(ok)
    apiMock.put.mockImplementation(ok)
    apiMock.delete.mockImplementation(ok)
  })

  it('getMemory 把行自带的 agent_id 发出去', async () => {
    await memoryApi.getMemory('mem_000001', 'kai')

    expect(apiMock.get).toHaveBeenCalledWith('/memory/mem_000001', {
      params: { agent_id: 'kai' },
    })
  })

  it('updateMemory 带 agent_id（否则 PUT 打到默认 Agent，编辑他人 Agent 的记忆必失败）', async () => {
    await memoryApi.updateMemory('mem_000001', { content: '改名' }, 'kai')

    expect(apiMock.put).toHaveBeenCalledWith(
      '/memory/mem_000001',
      { content: '改名' },
      { params: { agent_id: 'kai' } },
    )
  })

  it('deleteMemory 带 agent_id', async () => {
    await memoryApi.deleteMemory('mem_000001', 'kai')

    expect(apiMock.delete).toHaveBeenCalledWith('/memory/mem_000001', {
      params: { agent_id: 'kai' },
    })
  })

  it('不给 agent_id 时不虚构作用域（桌面单 Agent 路径仍走后端默认）', () => {
    memoryApi.getMemory('mem_000001')

    const config = apiMock.get.mock.calls[0]?.[1] as { params?: Record<string, unknown> } | undefined
    expect(config?.params?.agent_id).toBeUndefined()
  })

  it('列表面本来就带 agent_id（同模块两条腿不许只修一条）', () => {
    memoryApi.getMemories('kai', { query: '' })

    expect(apiMock.get).toHaveBeenCalledWith('/memory', {
      params: { query: '', agent_id: 'kai' },
    })
  })
})

describe('rowIsActionable：后端 owned 是唯一取源', () => {
  it('新符号存在（不猜第二份归属判定的前提）', () => {
    expect(typeof (memoryApi as Record<string, unknown>).rowIsActionable).toBe('function')
  })

  it('owned=false 的行不给动（服务端闸门对它就是 404）', () => {
    expect(memoryApi.rowIsActionable({ id: 'm1', owned: false })).toBe(false)
  })

  it('owned=true 的行给动', () => {
    expect(memoryApi.rowIsActionable({ id: 'm1', owned: true })).toBe(true)
  })

  it('后端没给 owned 字段时按可动作处理（只有显式 false 才禁，避免把没披露的列表打成人人禁用）', () => {
    expect(memoryApi.rowIsActionable({ id: 'm1' })).toBe(true)
  })
})
