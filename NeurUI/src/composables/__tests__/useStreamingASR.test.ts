import { afterEach, describe, expect, it, vi } from 'vitest'
import { buildAsrStreamUrl, floatToPcm16, resampleToPcm16 } from '../useStreamingASR'

afterEach(() => {
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
})

describe('floatToPcm16', () => {
  it('按小端编码并限幅', () => {
    const pcm = floatToPcm16(new Float32Array([0, 0.5, -0.5, 2, -2]))
    const view = new DataView(pcm)
    expect(view.getInt16(0, true)).toBe(0)
    expect(view.getInt16(2, true)).toBeCloseTo(0.5 * 0x7fff, -2)
    expect(view.getInt16(4, true)).toBeCloseTo(-0.5 * 0x8000, -2)
    expect(view.getInt16(6, true)).toBe(0x7fff) // 限幅
    expect(view.getInt16(8, true)).toBe(-0x8000) // 限幅
  })

  it('空输入得空缓冲', () => {
    expect(floatToPcm16(new Float32Array(0)).byteLength).toBe(0)
  })
})

describe('resampleToPcm16', () => {
  it('同采样率直通不重采样', () => {
    const input = new Float32Array([0.1, -0.1, 0.2])
    const pcm = resampleToPcm16(input, 16000, 16000)
    expect(pcm.byteLength).toBe(6)
  })

  it('48k→16k 三取一并保持包络走向', () => {
    // 48 个样本（48kHz 1ms）→ 16 个样本（16kHz 1ms）
    const input = new Float32Array(48)
    for (let i = 0; i < 48; i++) input[i] = i / 48
    const pcm = resampleToPcm16(input, 48000, 16000)
    expect(pcm.byteLength).toBe(16 * 2)
    const view = new DataView(pcm)
    const first = view.getInt16(0, true) / 0x7fff
    expect(first).toBeCloseTo(0, 1)
  })

  it('空输入得空缓冲', () => {
    expect(resampleToPcm16(new Float32Array(0), 48000, 16000).byteLength).toBe(0)
  })
})

describe('buildAsrStreamUrl', () => {
  it('相对 base 直接拼路径（浏览器按页面 origin 解析 WS）', () => {
    vi.stubEnv('VITE_API_BASE_URL', '/api/v1')
    expect(buildAsrStreamUrl()).toBe('/api/v1/audio/asr/stream')
  })

  it('绝对 http base 换 ws/wss 协议', () => {
    vi.stubEnv('VITE_API_BASE_URL', 'https://demo.example.com/api/v1')
    expect(buildAsrStreamUrl()).toBe('wss://demo.example.com/api/v1/audio/asr/stream')
  })

  it('携带 language 参数', () => {
    vi.stubEnv('VITE_API_BASE_URL', '/api/v1')
    expect(buildAsrStreamUrl('en')).toBe('/api/v1/audio/asr/stream?language=en')
    expect(buildAsrStreamUrl('zh')).toBe('/api/v1/audio/asr/stream?language=zh')
  })
})
