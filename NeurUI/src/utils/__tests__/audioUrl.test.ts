/**
 * resolveAudioUrl（F-4 配套，台账 2026-09-11）：
 * /api/ 鉴权内容端点 URL → 凭证据 fetch 转 objectURL；其余形态透传；
 * 取流失败返回 null（调用方不设 audioUrl，回落手动合成）。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { resolveAudioUrl } from '@/utils/audioUrl'
import { secureStorage } from '@/utils/security'

const createMock = vi.fn(() => 'blob:audio-test')
;(URL as unknown as Record<string, unknown>).createObjectURL = createMock

function okResp(body: string) {
  return {
    ok: true,
    blob: async () => new Blob([body]),
  }
}

beforeEach(() => {
  createMock.mockClear()
  vi.restoreAllMocks()
})

describe('resolveAudioUrl', () => {
  it('非 /api/ 形态原样透传（blob: 服务端直链/旧数据/空串）', async () => {
    const fetchSpy = vi.fn()
    expect(await resolveAudioUrl('blob:msg-1', fetchSpy)).toBe('blob:msg-1')
    expect(await resolveAudioUrl('https://cdn/x.wav', fetchSpy)).toBe('https://cdn/x.wav')
    expect(await resolveAudioUrl('', fetchSpy)).toBe('')
    expect(fetchSpy).not.toHaveBeenCalled()
  })

  it('/api/ URL：带 Bearer 取流 → objectURL', async () => {
    vi.spyOn(secureStorage, 'get').mockReturnValue('tok-abc')
    const fetchSpy = vi.fn(async () => okResp('aaa'))

    const url = await resolveAudioUrl('/api/v1/chat/tts-audio/a1/tts_s1_1.wav', fetchSpy)

    expect(url).toBe('blob:audio-test')
    expect(fetchSpy).toHaveBeenCalledWith(
      '/api/v1/chat/tts-audio/a1/tts_s1_1.wav',
      { headers: { Authorization: 'Bearer tok-abc' } },
    )
  })

  it('无 token：不带 Authorization 头仍可取流', async () => {
    vi.spyOn(secureStorage, 'get').mockReturnValue('')
    const fetchSpy = vi.fn(
      async (_u: string, _init?: { headers?: Record<string, string> }) => okResp('bbb'),
    )
    expect(await resolveAudioUrl('/api/x.wav', fetchSpy)).toBe('blob:audio-test')
    expect(fetchSpy.mock.calls[0][1]).toEqual({ headers: undefined })
  })

  it('HTTP 非 2xx → null（调用方回落手动合成，不设 audioUrl）', async () => {
    const fetchSpy = vi.fn(async () => ({ ok: false, blob: async () => new Blob() }))
    expect(await resolveAudioUrl('/api/x.wav', fetchSpy)).toBeNull()
    expect(createMock).not.toHaveBeenCalled()
  })

  it('0 字节 blob → null（requireNonEmptyAudioBlob 防线，416 根因不回归）', async () => {
    const fetchSpy = vi.fn(async () => okResp(''))
    expect(await resolveAudioUrl('/api/x.wav', fetchSpy)).toBeNull()
  })

  it('fetch 抛错 → null（静默回落，不抛出）', async () => {
    const fetchSpy = vi.fn(async () => {
      throw new Error('network down')
    })
    expect(await resolveAudioUrl('/api/x.wav', fetchSpy)).toBeNull()
  })
})
