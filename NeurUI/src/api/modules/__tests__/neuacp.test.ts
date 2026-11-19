/**
 * neuacp API 模块契约测试（ACP 外部编码代理接入 B6）
 *
 * 钉住外部编码代理管理面四条通道的 URL/方法/载荷（设计文档 §4.7 / §4.1）：
 * - GET    /external-agents/catalog   工具目录（含本机安装探测）
 * - POST   /external-agents/test      握手级连通测试（body = executor 配置）
 * - GET    /external-agents/status    进程池状态
 * - DELETE /teams/{id}/members/{member_id}  名册移除（复用 teams 端点，A5）
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('@/api', () => ({
  default: {
    get: vi.fn().mockResolvedValue({}),
    post: vi.fn().mockResolvedValue({}),
    put: vi.fn().mockResolvedValue({}),
    delete: vi.fn().mockResolvedValue({}),
  },
}))

import api from '@/api'
import {
  fetchNeuacpCatalog,
  testNeuacpConnection,
  fetchNeuacpStatus,
  removeTeamMember,
} from '@/api/modules/neuacp'

const mockGet = vi.mocked(api.get)
const mockPost = vi.mocked(api.post)
const mockDelete = vi.mocked(api.delete)

beforeEach(() => {
  vi.clearAllMocks()
})

describe('neuacp API — 管理面三通道', () => {
  it('fetchNeuacpCatalog calls GET /external-agents/catalog', async () => {
    await fetchNeuacpCatalog()
    expect(mockGet).toHaveBeenCalledTimes(1)
    expect(mockGet.mock.calls[0][0]).toBe('/external-agents/catalog')
  })

  it('testNeuacpConnection calls POST /external-agents/test with executor body verbatim', async () => {
    const executor = {
      kind: 'acp' as const,
      tool: 'opencode',
      transport: 'stdio' as const,
      command: ['opencode', 'acp'],
      cwd: 'E:/workspace/demo',
      env_keys: ['OPENCODE_API_KEY'],
      permission_mode: 'chain' as const,
      remote: null,
    }
    await testNeuacpConnection(executor)
    expect(mockPost).toHaveBeenCalledTimes(1)
    const [url, body] = mockPost.mock.calls[0]
    expect(String(url)).toBe('/external-agents/test')
    expect(body).toEqual(executor)
  })

  it('fetchNeuacpStatus calls GET /external-agents/status', async () => {
    await fetchNeuacpStatus()
    expect(mockGet).toHaveBeenCalledTimes(1)
    expect(mockGet.mock.calls[0][0]).toBe('/external-agents/status')
  })
})

describe('neuacp API — 名册移除（A5 DELETE 端点）', () => {
  it('removeTeamMember calls DELETE /teams/{id}/members/{member_id}', async () => {
    await removeTeamMember('team-1', 'acp-opencode-1')
    expect(mockDelete).toHaveBeenCalledTimes(1)
    expect(mockDelete.mock.calls[0][0]).toBe('/teams/team-1/members/acp-opencode-1')
  })

  it('memberId 含特殊字符时按路径段转义（后端按路径参数取件）', async () => {
    await removeTeamMember('team-1', 'a/b c')
    expect(mockDelete).toHaveBeenCalledTimes(1)
    expect(mockDelete.mock.calls[0][0]).toBe(
      `/teams/team-1/members/${encodeURIComponent('a/b c')}`,
    )
  })
})
