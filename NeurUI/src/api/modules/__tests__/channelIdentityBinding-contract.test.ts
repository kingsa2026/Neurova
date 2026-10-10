/**
 * 渠道身份绑定 API 客户端契约（工单 2026-10-10 批 4b）。
 *
 * 钉三件事：
 * 1. 三条请求的路径/方法/参数形状与后端路由一致（跨语言逐字比对，不靠"看起来一样"）；
 * 2. 发码请求体**只有** (agent_id, channel_type) 两个键——归属由服务端按登录态填，
 *    前端一旦能带 `user_id`，就等于把"这个渠道身份算谁"交给点面板的人；
 * 3. 后端返回裸对象（与 ingress/migration-sources 同形），客户端不再套一层 `data`。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

vi.mock('@/api', () => ({
  default: {
    get: vi.fn().mockResolvedValue({ bindings: [] }),
    post: vi.fn().mockResolvedValue({ code: '123456' }),
    delete: vi.fn().mockResolvedValue({ revoked: true }),
  },
}))

import api from '@/api'
import {
  issueChannelBindingCode, listChannelIdentityBindings, revokeChannelIdentityBinding,
} from '@/api/modules/channel-configs'

const get = api.get as unknown as ReturnType<typeof vi.fn>
const post = api.post as unknown as ReturnType<typeof vi.fn>
const del = api.delete as unknown as ReturnType<typeof vi.fn>

const BASE = '/channel-configs'

beforeEach(() => {
  vi.clearAllMocks()
})

describe('请求形状', () => {
  it('列表按 agent 取数', async () => {
    await listChannelIdentityBindings('kai')
    expect(get).toHaveBeenCalledWith(`${BASE}/identity/bindings`, { params: { agent_id: 'kai' } })
  })

  it('发码体只有 (agent_id, channel_type)——不可能带上归属', async () => {
    await issueChannelBindingCode('kai', 'feishu')

    expect(post).toHaveBeenCalledTimes(1)
    const [path, body] = post.mock.calls[0]
    expect(path).toBe(`${BASE}/identity/bindings/code`)
    expect(Object.keys(body as object).sort()).toEqual(['agent_id', 'channel_type'])
  })

  it('解绑带上 (agent, 渠道, 发送者) 三元组', async () => {
    await revokeChannelIdentityBinding({
      agent_id: 'kai', channel_type: 'feishu', channel_user_id: 'ou_9',
    })

    expect(del).toHaveBeenCalledWith(`${BASE}/identity/bindings`, {
      params: { agent_id: 'kai', channel_type: 'feishu', channel_user_id: 'ou_9' },
    })
  })
})

/**
 * 前端写的三条路径必须在后端路由文件里真存在（改一边忘一边是本仓跨语言面的老毛病：
 * 前端 404 而后端只是换了个名字，用户看到的是"功能没了"）。
 */
describe('与后端路由逐字同形', () => {
  const backend = readFileSync(
    resolve(process.cwd(), '..', 'neurova', 'api', 'endpoints', 'channel_config.py'), 'utf-8',
  ).replace(/\r\n/g, '\n')

  it.each([
    ['列表', 'get', '"/identity/bindings"'],
    ['发码', 'post', '"/identity/bindings/code"'],
    ['解绑', 'delete', '"/identity/bindings"'],
  ])('%s 端点在后端仍在（%s %s）', (_name, method, literal) => {
    expect(backend, `后端 @router.${method}(${literal}) 消失或改名`)
      .toContain(`@router.${method}(${literal}`)
  })

  it('后端不存在"指定账号去绑"的 POST 入口（前端也就无从带 user_id）', () => {
    expect(backend).not.toContain('@router.post("/identity/bindings",')
  })
})
