/**
 * 管理通道接线：管理员的按 id 寻址走 `/memory/management/{id}`（承 §6-425 那张需人裁票的裁定）
 *
 * 后端新开了一条带 role 门的 agent-wide 通道（`tests/integration/test_memoryManagementChannelRoleGate.py`
 * 钉它的授权语义）。前端这一半要接上的不是"能不能动"（那仍由后端逐条给的 `owned` 说话，
 * 管理员现在拿到 owned=true），而是**用哪条通道去动**：
 * - 管理员 ⇒ 按 id 的读／改／删必须打到 `/memory/management/{id}`，因为常规路对他人行仍
 *   "视同不存在"（老门没被放宽，这是裁定的前提）；
 * - 普通用户 ⇒ 保持打常规路，一条请求都不许多发。
 *
 * 路径只在一处构造（`memoryPath`），三个函数共用——否则就是两份寻址实现，
 * 改一处漏一处（本仓同型病：列表腿带 agent_id、按 id 的三条不带）。
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
import memorySource from '@/api/modules/memory.ts?raw'

const ok = (data: unknown = {}) => Promise.resolve({ code: 0, data })

describe('按 id 寻址的两条通道', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    apiMock.get.mockImplementation(ok)
    apiMock.put.mockImplementation(ok)
    apiMock.delete.mockImplementation(ok)
  })

  it('默认走常规路（老门语义不变）', async () => {
    await memoryApi.getMemory('mem_1', 'kai')

    expect(apiMock.get).toHaveBeenCalledWith('/memory/mem_1', { params: { agent_id: 'kai' } })
  })

  it('management 选项把读打到管理通道，且作用域参数照带', async () => {
    await memoryApi.getMemory('mem_1', 'kai', { management: true })

    expect(apiMock.get).toHaveBeenCalledWith('/memory/management/mem_1', {
      params: { agent_id: 'kai' },
    })
  })

  it('management 选项把改打到管理通道（他人行只有这条通道收）', async () => {
    await memoryApi.updateMemory('mem_1', { content: '管理员代改' }, 'kai', { management: true })

    expect(apiMock.put).toHaveBeenCalledWith(
      '/memory/management/mem_1',
      { content: '管理员代改' },
      { params: { agent_id: 'kai' } },
    )
  })

  it('management 选项把删打到管理通道', async () => {
    await memoryApi.deleteMemory('mem_1', 'kai', { management: true })

    expect(apiMock.delete).toHaveBeenCalledWith('/memory/management/mem_1', {
      params: { agent_id: 'kai' },
    })
  })

  it('路径只在一处构造（不许出现第二份 /management/ 拼接）', () => {
    // 剔注释再数：形状判据按行匹配会被自己的文档措辞撞红（本仓形态 414/427 同族——
    // 上一版就是被 memory.ts 里那句"管理通道 `/memory/management/{id}`"的注释顶红的）。
    const code = memorySource.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/[^\n]*/g, '')

    expect((code.match(/\/management\//g) ?? []).length).toBe(1)
  })
})
