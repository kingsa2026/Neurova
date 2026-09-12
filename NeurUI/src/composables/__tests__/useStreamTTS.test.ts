/**
 * useStreamTTS 纯函数与流水线测试（流式实时 TTS 补课）。
 *
 * 契约：
 * - sanitizeForSpeech：网址/围栏代码/行内代码/表情/md 链接剥离
 * - extractSentences：句末标点切分 + 短句滞留 + force 收尾
 * - Runner：保序串行合成、过滤空句、abort 保留已合成 url、onDone 定稿
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  StreamTTSRunner,
  audioSourceFor,
  extractSentences,
  requireNonEmptyAudioBlob,
  sanitizeForSpeech,
} from '@/composables/useStreamTTS'

describe('audioSourceFor（回放 src 选取）', () => {
  it('有 ttsUrls 时按 ttsIdx 取句块（播放器逐句回放）', () => {
    const msg = { ttsUrls: ['blob:0', 'blob:1'], ttsIdx: 1 }
    expect(audioSourceFor(msg)).toBe('blob:1')
  })

  it('ttsIdx 越界回落首块（避免 <audio> 拿到空 src）', () => {
    const msg = { ttsUrls: ['blob:0', 'blob:1'], ttsIdx: 99 }
    expect(audioSourceFor(msg)).toBe('blob:0')
  })

  it('无 ttsUrls 时回落 audioUrl（手动单段 TTS）', () => {
    expect(audioSourceFor({ audioUrl: 'blob:full' })).toBe('blob:full')
  })

  it('两者皆无返回空串', () => {
    expect(audioSourceFor({})).toBe('')
  })
})

describe('requireNonEmptyAudioBlob', () => {
  it('rejects empty blob (0 字节 → <audio> 416 根因)', () => {
    expect(() => requireNonEmptyAudioBlob(new Blob([]))).toThrow()
    expect(() => requireNonEmptyAudioBlob(new Blob(['']))).toThrow()
  })

  it('passes through non-empty blob', () => {
    const blob = new Blob([new Uint8Array([0xff, 0xf3, 0x64])], { type: 'audio/mpeg' })
    expect(requireNonEmptyAudioBlob(blob)).toBe(blob)
  })
})

describe('sanitizeForSpeech', () => {
  it('strips urls', () => {
    expect(sanitizeForSpeech('看这个 https://example.com/a?b=1 很好')).toBe('看这个 很好')
    expect(sanitizeForSpeech('访问 www.foo.bar 即可')).toBe('访问 即可')
  })

  it('strips fenced and inline code', () => {
    expect(sanitizeForSpeech('运行 ```npm install foo``` 然后')).toBe('运行 然后')
    expect(sanitizeForSpeech('用 `npm run dev` 启动')).toBe('用 启动')
  })

  it('strips emojis including ZWJ sequences', () => {
    expect(sanitizeForSpeech('好的👍没问题')).toBe('好的没问题')
    expect(sanitizeForSpeech('家庭👨‍👩‍👧多样')).toBe('家庭多样')
  })

  it('keeps markdown link text, drops residue symbols', () => {
    expect(sanitizeForSpeech('见[文档](https://x.y)说明')).toBe('见文档说明')
    expect(sanitizeForSpeech('**重点** 内容')).toBe('重点 内容')
  })

  it('collapses whitespace', () => {
    expect(sanitizeForSpeech('a\n\n  b')).toBe('a b')
  })
})

describe('extractSentences', () => {
  it('splits on sentence-final punctuation with min-length merge', () => {
    const { complete, rest } = extractSentences(
      '这句话已经足够长到可以直接合成了。第二句话也足够长输出没有问题！尾巴',
    )
    expect(complete).toHaveLength(2)
    expect(rest).toBe('尾巴')
  })

  it('holds back short sentences for merging', () => {
    // "好。" 清洗后不足 12 字 → 滞留与后句合并
    const { complete } = extractSentences('好。这是一段足够长的话可以作为完整句子输出。')
    expect(complete).toHaveLength(1)
    expect(complete[0]).toContain('好。')
  })

  it('force flushes remaining buffer', () => {
    const { complete, rest } = extractSentences('没有结尾的尾巴', true)
    expect(complete).toEqual(['没有结尾的尾巴'])
    expect(rest).toBe('')
  })

  it('handles newline as sentence end (merged when short)', () => {
    const { complete } = extractSentences(
      '第一段的内容到这里就已经完整结束了。\n第二段内容足够长可以独立成句输出给合成器了。',
    )
    expect(complete).toHaveLength(2)
    expect(complete[0].startsWith('第一段')).toBe(true)
  })
})

describe('StreamTTSRunner', () => {
  let hooks: {
    synthesize: ReturnType<typeof vi.fn>
    onChunkReady: ReturnType<typeof vi.fn>
    onDone: ReturnType<typeof vi.fn>
  }

  beforeEach(() => {
    hooks = {
      synthesize: vi.fn(async (text: string) => `blob:${encodeURIComponent(text)}`),
      onChunkReady: vi.fn(),
      onDone: vi.fn(),
    }
  })

  it('synthesizes sentences in order (serial chain)', async () => {
    const runner = new StreamTTSRunner(hooks)
    runner.begin()
    runner.feed('第一句话已经完整输出可以直接送去合成了。第二句话同样完整')
    runner.feed('地结束了，长度也足够。')
    runner.end()
    await vi.waitFor(() => expect(hooks.onDone).toHaveBeenCalled())
    const calls = hooks.synthesize.mock.calls.map((c) => c[0])
    expect(calls.length).toBeGreaterThanOrEqual(2)
    // 保序：第一句在第二句之前
    expect(calls[0].includes('第一句')).toBe(true)
    expect(hooks.onChunkReady.mock.calls[0][1]).toBe(0)
  })

  it('skips speech-empty sentences (url/code/emoji only)', async () => {
    const runner = new StreamTTSRunner(hooks)
    runner.begin()
    runner.feed('这里是链接 https://a.b/c 和代码 `npm i` 的组合，后面还有一句正常话要说完。')
    runner.end()
    await vi.waitFor(() => expect(hooks.onDone).toHaveBeenCalled())
    // 合成请求里不应包含 url/代码痕迹
    for (const call of hooks.synthesize.mock.calls) {
      expect(call[0]).not.toMatch(/https?:\/\//)
      expect(call[0]).not.toMatch(/`/)
    }
  })

  it('keeps unconsumed tail when sentences are newline-separated (F-04 回归)', async () => {
    // 修复前：trim 后的句子拼接与原 buffer 失配（句间 \n\n），indexOf=-1 →
    // 整个 buffer（含未分句的尾巴）被清空 → 尾部文本静默丢弃。
    const runner = new StreamTTSRunner(hooks)
    runner.begin()
    runner.feed('第一句话足够长可以送去合成了。\n\n第二句话足够长也可以送去合成了。\n\n这是没有句号的尾巴文本')
    runner.end()
    await vi.waitFor(() => expect(hooks.onDone).toHaveBeenCalled())
    const calls = hooks.synthesize.mock.calls.map((c) => c[0])
    expect(calls.some((txt) => txt.includes('第一句'))).toBe(true)
    // 尾巴必须被 force 出句送合成（修复前被误清空丢失）
    expect(calls.some((txt) => txt.includes('尾巴文本'))).toBe(true)
  })

  it('abort keeps already-synthesized urls and stops new synthesis', async () => {
    let releaseFirst: (() => void) | null = null
    hooks.synthesize.mockImplementationOnce(
      (_text: string, signal: AbortSignal) =>
        new Promise<string>((resolve) => {
          const t = setTimeout(() => resolve('blob:first'), 50)
          signal.addEventListener('abort', () => {
            clearTimeout(t)
            resolve('blob:first-aborted')
          })
          void releaseFirst
        }),
    )
    const runner = new StreamTTSRunner(hooks)
    runner.begin()
    runner.feed('第一句很长可以合成了。第二句也很长可以合成了。')
    // 等第一句入链后 abort
    await vi.waitFor(() => expect(hooks.synthesize).toHaveBeenCalled())
    runner.abort()
    await new Promise((r) => setTimeout(r, 10))
    const afterAbort = hooks.synthesize.mock.calls.length
    await new Promise((r) => setTimeout(r, 30))
    // abort 后不再发起新合成
    expect(hooks.synthesize.mock.calls.length).toBeLessThanOrEqual(afterAbort + 1)
  })
})

// ── 台账 N6（2026-09-11）：语音提示播报打断/销毁不泄漏 object URL ──
// 旧实现被打断的上一条播报 pause 后 onended 永不触发，object URL 每次打断
// 泄漏一个；dispose 同样只 pause 不回收。根修：打断/销毁路径显式 revoke。
describe('createSpeechAnnouncer object URL 回收（N6）', () => {
  let createCalls: string[]
  let revokeMock: ReturnType<typeof vi.fn>
  interface FakeAudioInstance { src: string; paused: boolean; onended: (() => void) | null; play: ReturnType<typeof vi.fn>; pause: ReturnType<typeof vi.fn> }
  let audioInstances: FakeAudioInstance[]

  function FakeAudio(this: unknown, src: string) {
    const self = this as Record<string, unknown>
    self.src = src
    self.paused = false
    self.onended = null
    self.play = vi.fn().mockResolvedValue(undefined)
    self.pause = vi.fn(() => { self.paused = true })
    audioInstances.push(self as unknown as FakeAudioInstance)
  }

  beforeEach(async () => {
    vi.resetModules()
    audioInstances = []
    createCalls = []
    revokeMock = vi.fn()
    ;(URL as unknown as Record<string, unknown>).createObjectURL = vi.fn(() => `blob:announce-${createCalls.push('x')}`)
    ;(URL as unknown as Record<string, unknown>).revokeObjectURL = revokeMock
    Object.defineProperty(globalThis, 'Audio', { value: FakeAudio, configurable: true, writable: true });
    // 动态引入保证 stub 先于模块加载生效
    ({ createSpeechAnnouncer } = await import('@/composables/useStreamTTS'))
  })

  let createSpeechAnnouncer: (typeof import('@/composables/useStreamTTS'))['createSpeechAnnouncer']

  it('播报被打断：上一条 object URL 被显式 revoke', async () => {
    const announcer = createSpeechAnnouncer(async (t) => new Blob([t]), { enabled: () => true })
    announcer.announce('第一条')
    await vi.waitFor(() => expect(audioInstances.length).toBe(1))
    announcer.announce('第二条')
    await vi.waitFor(() => expect(audioInstances.length).toBe(2))
    // 第一条被 pause 且其 URL 已回收
    expect(audioInstances[0].paused).toBe(true)
    expect(revokeMock).toHaveBeenCalledWith('blob:announce-1')
    announcer.dispose()
  })

  it('dispose：当前播报 pause 且 URL 被回收', async () => {
    const announcer = createSpeechAnnouncer(async (t) => new Blob([t]), { enabled: () => true })
    announcer.announce('只此一条')
    await vi.waitFor(() => expect(audioInstances.length).toBe(1))
    announcer.dispose()
    expect(audioInstances[0].paused).toBe(true)
    expect(revokeMock).toHaveBeenCalledWith('blob:announce-1')
  })

  it('自然播完路径不受影响（onended 仍回收自身 URL）', async () => {
    const announcer = createSpeechAnnouncer(async (t) => new Blob([t]), { enabled: () => true })
    announcer.announce('播完')
    await vi.waitFor(() => expect(audioInstances.length).toBe(1))
    audioInstances[0].onended?.()
    expect(revokeMock).toHaveBeenCalledWith('blob:announce-1')
    announcer.dispose()
    // 已被 onended 回收，dispose 不重复计数（幂等 no-op）
    expect(revokeMock).toHaveBeenCalledTimes(1)
  })
})
