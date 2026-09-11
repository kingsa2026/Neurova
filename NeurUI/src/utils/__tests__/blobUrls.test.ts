/**
 * revokeMessageBlobUrls — 消息 blob URL 生命周期助手（P1-10 防回归）。
 *
 * 契约：
 * 1. 只 revoke `blob:` 前缀的 URL（audioUrl / ttsUrls[] / attachments[].preview）；
 * 2. 非 blob URL（http/data:）与缺失字段一律跳过，不抛错（null/undefined 安全）；
 * 3. 重复调用安全（URL.revokeObjectURL 对已 revoke 的 URL 是规范定义的 no-op）。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { revokeMessageBlobUrls } from '@/utils/blobUrls'

const revokeMock = vi.fn()

function setUrlStub(): void {
  ;(URL as unknown as Record<string, unknown>).revokeObjectURL = revokeMock
}

describe('revokeMessageBlobUrls（P1-10）', () => {
  beforeEach(() => {
    revokeMock.mockClear()
    setUrlStub()
  })

  it('revoke 消息上全部三类 blob URL（audioUrl/ttsUrls/attachments[].preview）', () => {
    revokeMessageBlobUrls({
      audioUrl: 'blob:audio-1',
      ttsUrls: ['blob:tts-1', 'blob:tts-2'],
      attachments: [{ name: 'a.png', preview: 'blob:preview-1' }, { name: 'b.txt' }],
    })
    expect(revokeMock).toHaveBeenCalledTimes(4)
    expect(revokeMock).toHaveBeenCalledWith('blob:audio-1')
    expect(revokeMock).toHaveBeenCalledWith('blob:tts-1')
    expect(revokeMock).toHaveBeenCalledWith('blob:tts-2')
    expect(revokeMock).toHaveBeenCalledWith('blob:preview-1')
  })

  it('跳过非 blob URL（http/data:）与空串', () => {
    revokeMessageBlobUrls({
      audioUrl: 'https://example.com/a.wav',
      ttsUrls: ['data:audio/wav;base64,AAAA', ''],
      attachments: [{ preview: '/files/1/preview' }],
    })
    expect(revokeMock).not.toHaveBeenCalled()
  })

  it('缺失字段 / null / undefined 均安全', () => {
    expect(() => revokeMessageBlobUrls(undefined)).not.toThrow()
    expect(() => revokeMessageBlobUrls(null)).not.toThrow()
    expect(() => revokeMessageBlobUrls({})).not.toThrow()
    expect(() => revokeMessageBlobUrls({ audioUrl: undefined, ttsUrls: [], attachments: [] })).not.toThrow()
    expect(revokeMock).not.toHaveBeenCalled()
  })

  it('同一 URL 既是 audioUrl 又是 ttsUrls[0]（流式 TTS 回放场景）不抛错', () => {
    expect(() =>
      revokeMessageBlobUrls({ audioUrl: 'blob:same', ttsUrls: ['blob:same'] }),
    ).not.toThrow()
    // revokeObjectURL 幂等，重复调用无害
    expect(revokeMock).toHaveBeenCalledWith('blob:same')
  })
})
