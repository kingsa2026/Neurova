/**
 * F-1 契约对齐测试：media.ts 的调用路径与载荷必须命中后端 media.py 真实路由。
 *
 * 台账 docs/资源型修复登记台账_2026-09-11.md F-1（系统性契约错位）：
 * - listMedia → GET /media/list（offset/limit 参数；响应 data.media/total/offset/limit）；
 * - getMediaInfo → GET /media/{id}/metadata（原 /{id}/info 404）；
 * - downloadMedia → GET /media/download/{id}（原 /{id}/download 404）；
 * - batchDeleteMedia → POST /media/batch-delete，body { media_ids }（原 /batch-delete 404）；
 * - saveMedia 必须携带后端必填的 media_type 表单字段（缺省 422）；
 * - getMediaStats 已移除（后端无 /stats?agent_id= 查询参数版本，UI 也无统计展示）。
 *
 * 用 vi.mock('@/api') 捕获请求（不依赖网络），响应载荷采用后端真实形状。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/api', () => {
  const api = { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() }
  const request = { get: vi.fn(), post: vi.fn() }
  // media.ts 同时使用 default import（api）与命名 import（request）
  return { default: api, api, request }
})

import { api, request } from '@/api'
import * as mediaApi from '../modules/media'

const apiGet = vi.mocked(api.get)
const apiPost = vi.mocked(api.post)
const apiPut = vi.mocked(api.put)
const apiDelete = vi.mocked(api.delete)
const requestGet = vi.mocked(request.get)

beforeEach(() => {
  vi.clearAllMocks()
})

describe('listMedia（后端 GET /media/list 契约）', () => {
  it('以 offset/limit/agent_id/media_type 查询参数请求 /media/list', async () => {
    const envelope = {
      code: 0,
      message: 'ok',
      data: {
        media: [
          {
            media_id: 'media-abc123',
            filename: 'clip.png',
            media_type: 'image',
            mime_type: 'image/png',
            size: 14,
            agent_id: 'a1',
            user_id: null,
            memory_id: null,
            storage_path: 'media_storage/a1/image/media-abc123_clip.png',
            created_at: 1760000000.5,
            metadata: {},
          },
        ],
        total: 1,
        offset: 0,
        limit: 50,
      },
    }
    apiGet.mockResolvedValue(envelope)

    const res = await mediaApi.listMedia({ agent_id: 'a1', media_type: 'image', offset: 0, limit: 50 })

    expect(apiGet).toHaveBeenCalledWith('/media/list', {
      params: { agent_id: 'a1', media_type: 'image', offset: 0, limit: 50 },
    })
    // 响应解包：拦截器返回 {code,message,data} 信封，页面消费 res.data.media
    expect(res).toBe(envelope)
    expect(res.data.media[0].media_id).toBe('media-abc123')
    expect(res.data.media[0]).not.toHaveProperty('url')
    expect(res.data.media[0]).not.toHaveProperty('tags')
  })
})

describe('saveMedia（后端 POST /media/save 契约）', () => {
  it('必须携带后端必填的 media_type（由 file MIME 推导）与 agent_id', async () => {
    apiPost.mockResolvedValue({ code: 0, message: 'ok', data: {} })
    const file = new File([new Uint8Array([1, 2, 3])], 'photo.png', { type: 'image/png' })

    await mediaApi.saveMedia(file, 'a1')

    expect(apiPost).toHaveBeenCalledTimes(1)
    const [url, body] = apiPost.mock.calls[0]
    expect(url).toBe('/media/save')
    const fd = body as FormData
    expect(fd.get('file')).toBeInstanceOf(File)
    expect(fd.get('media_type')).toBe('image')
    expect(fd.get('agent_id')).toBe('a1')
  })

  it('非媒体 MIME 回退为 file 类型', async () => {
    apiPost.mockResolvedValue({ code: 0, message: 'ok', data: {} })
    const file = new File([new Uint8Array([1])], 'notes.txt', { type: 'text/plain' })

    await mediaApi.saveMedia(file)

    const fd = apiPost.mock.calls[0][1] as FormData
    expect(fd.get('media_type')).toBe('file')
    expect(fd.has('agent_id')).toBe(false)
  })
})

describe('详情 / 下载 / 删除（后端真实路由）', () => {
  it('getMediaInfo 命中 GET /media/{id}/metadata（原 /{id}/info 404）', async () => {
    apiGet.mockResolvedValue({ code: 0, message: 'ok', data: { media_id: 'm1' } })
    await mediaApi.getMediaInfo('m1')
    expect(apiGet).toHaveBeenCalledWith('/media/m1/metadata')
  })

  it('downloadMedia 命中 GET /media/download/{id}（原 /{id}/download 404）并取 blob', async () => {
    const blob = new Blob([new Uint8Array([9, 9])], { type: 'audio/wav' })
    requestGet.mockResolvedValue(blob)
    const out = await mediaApi.downloadMedia('m1')
    expect(requestGet).toHaveBeenCalledWith('/media/download/m1', { responseType: 'blob' })
    expect(out).toBe(blob)
  })

  it('getMedia 命中 GET /media/{id} 并取 blob', async () => {
    const blob = new Blob([new Uint8Array([1])], { type: 'image/png' })
    requestGet.mockResolvedValue(blob)
    const out = await mediaApi.getMedia('m1')
    expect(requestGet).toHaveBeenCalledWith('/media/m1', { responseType: 'blob' })
    expect(out).toBe(blob)
  })

  it('deleteMedia 命中 DELETE /media/{id}', async () => {
    apiDelete.mockResolvedValue({ code: 0, message: 'ok', data: null })
    await mediaApi.deleteMedia('m1')
    expect(apiDelete).toHaveBeenCalledWith('/media/m1')
  })
})

describe('batchDeleteMedia（后端 POST /media/batch-delete 契约）', () => {
  it('以 { media_ids } 为 body 请求 /media/batch-delete，回报 succeeded/failed', async () => {
    const envelope = {
      code: 0,
      message: 'ok',
      data: { succeeded: ['m1'], failed: [{ media_id: 'm2', reason: 'media not found' }] },
    }
    apiPost.mockResolvedValue(envelope)

    const res = await mediaApi.batchDeleteMedia(['m1', 'm2'])

    expect(apiPost).toHaveBeenCalledWith('/media/batch-delete', { media_ids: ['m1', 'm2'] })
    expect(res.data.succeeded).toEqual(['m1'])
    expect(res.data.failed[0].media_id).toBe('m2')
  })
})

describe('已移除的错位调用', () => {
  it('getMediaStats 已移除（后端无 /stats?agent_id= 查询参数版本，UI 无统计展示）', () => {
    expect((mediaApi as Record<string, unknown>).getMediaStats).toBeUndefined()
  })
})

describe('config（后端 GET/PUT /media/config 契约）', () => {
  it('getMediaConfig 命中 GET /media/config', async () => {
    apiGet.mockResolvedValue({ code: 0, message: 'ok', data: { max_file_size: 1 } })
    await mediaApi.getMediaConfig()
    expect(apiGet).toHaveBeenCalledWith('/media/config')
  })

  it('updateMediaConfig 命中 PUT /media/config', async () => {
    apiPut.mockResolvedValue({ code: 0, message: 'ok', data: {} })
    await mediaApi.updateMediaConfig({ max_file_size: 1024 })
    expect(apiPut).toHaveBeenCalledWith('/media/config', { max_file_size: 1024 })
  })
})
