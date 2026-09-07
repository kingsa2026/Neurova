/**
 * prepareSpeechText / toolAnnouncementText / createSpeechAnnouncer 测试
 * （2026-09-07 用户需求：代码/网址/图片/视频播报提示 + 工具执行语音提示）
 *
 * 契约：
 * - prepareSpeechText：围栏/行内代码→"以下是代码。"，网址→"以下是网址。"，
 *   图片→"以下是图片[：alt]。"，视频外链→"以下是视频。"；表情/md残留仍剔除
 * - sanitizeForSpeech：旧契约保留（全部剔除）
 * - toolAnnouncementText：shell/命令类→"正在执行命令，请稍等"；其余→"正在使用工具，请稍等"
 * - createSpeechAnnouncer：同文本 8s 冷却；disabled 不播；blob 合成失败静默
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'
import {
  prepareSpeechText,
  sanitizeForSpeech,
  toolAnnouncementText,
  createSpeechAnnouncer,
} from '@/composables/useStreamTTS'

describe('prepareSpeechText（内容改播报提示）', () => {
  it('围栏代码块 → 以下是代码。', () => {
    const out = prepareSpeechText('看这段：\n```python\nprint(1)\n```\n结束')
    expect(out).toContain('以下是代码')
    expect(out).not.toContain('print')
    expect(out).not.toContain('```')
  })

  it('行内代码 → 以下是代码。', () => {
    const out = prepareSpeechText('用 `npm run dev` 启动')
    expect(out).toContain('以下是代码')
    expect(out).not.toContain('npm')
  })

  it('网址 → 以下是网址。', () => {
    const out = prepareSpeechText('官网是 https://www.neurova.top/docs 欢迎访问')
    expect(out).toContain('以下是网址')
    expect(out).not.toContain('neurova.top')
  })

  it('裸 www 网址同样播报', () => {
    const out = prepareSpeechText('去 www.example.com 看看')
    expect(out).toContain('以下是网址')
    expect(out).not.toContain('example.com')
  })

  it('markdown 图片 → 以下是图片（带 alt 描述）', () => {
    const out = prepareSpeechText('结果如图 ![架构图](https://x.com/a.png)')
    expect(out).toContain('以下是图片：架构图')
    expect(out).not.toContain('x.com')
  })

  it('无 alt 图片 → 以下是图片。', () => {
    const out = prepareSpeechText('![](https://x.com/b.png)')
    expect(out).toContain('以下是图片。')
  })

  it('视频外链 → 以下是视频。', () => {
    const out = prepareSpeechText('演示视频 https://cdn.x.com/demo.mp4 已生成')
    expect(out).toContain('以下是视频')
    expect(out).not.toContain('demo.mp4')
  })

  it('markdown 链接读链接文本（URL 已随链接语法消失，无需再播报网址）', () => {
    const out = prepareSpeechText('参考 [使用文档](https://x.com/doc)')
    expect(out).toContain('使用文档')
    expect(out).not.toContain('x.com')
  })

  it('表情与 md 残留剔除，纯符号返回空串', () => {
    expect(prepareSpeechText('你好 😀 世界')).not.toContain('😀')
    expect(prepareSpeechText('*# >')).toBe('')
  })

  it('普通正文原样保留（只收空白）', () => {
    const out = prepareSpeechText('今天  天气不错。')
    expect(out).toBe('今天 天气不错。')
  })

  it('旧契约 sanitizeForSpeech 保留：网址/代码全部剔除不播报', () => {
    expect(sanitizeForSpeech('看 https://x.com 和 `code`')).not.toContain('x.com')
    expect(sanitizeForSpeech('```js\nvar a=1\n```')).toBe('')
  })
})

describe('toolAnnouncementText（工具/命令分语）', () => {
  it('命令类工具说"正在执行命令，请稍等"', () => {
    expect(toolAnnouncementText('computer_shell')).toBe('正在执行命令，请稍等')
    expect(toolAnnouncementText('run_code')).toBe('正在执行命令，请稍等')
  })

  it('其余工具说"正在使用工具，请稍等"', () => {
    expect(toolAnnouncementText('web_search')).toBe('正在使用工具，请稍等')
    expect(toolAnnouncementText('memory_search')).toBe('正在使用工具，请稍等')
  })
})

describe('createSpeechAnnouncer（独立分轨提示）', () => {
  beforeEach(() => {
    // jsdom 无 Audio 实现：桩一个可断言的最小对象
    vi.stubGlobal(
      'Audio',
      vi.fn().mockImplementation(() => ({ play: vi.fn().mockResolvedValue(undefined), pause: vi.fn() })),
    )
    vi.stubGlobal('URL', { ...URL, createObjectURL: vi.fn(() => 'blob:mock'), revokeObjectURL: vi.fn() })
  })

  it('同文本 8s 冷却内只合成一次', async () => {
    vi.useFakeTimers()
    const synth = vi.fn().mockResolvedValue(new Blob(['a']))
    const { announce } = createSpeechAnnouncer(synth)
    announce('正在执行命令，请稍等')
    announce('正在执行命令，请稍等')
    await vi.runAllTimersAsync()
    expect(synth).toHaveBeenCalledTimes(1)
    vi.useRealTimers()
  })

  it('enabled=false 时不合成', async () => {
    const synth = vi.fn()
    const { announce } = createSpeechAnnouncer(synth, { enabled: () => false })
    announce('任何提示')
    await new Promise((r) => setTimeout(r, 0))
    expect(synth).not.toHaveBeenCalled()
  })

  it('合成失败静默（不抛错）', async () => {
    const synth = vi.fn().mockRejectedValue(new Error('network'))
    const { announce } = createSpeechAnnouncer(synth)
    expect(() => announce('提示')).not.toThrow()
    await new Promise((r) => setTimeout(r, 0))
  })

  it('空文本直接跳过', () => {
    const synth = vi.fn()
    const { announce } = createSpeechAnnouncer(synth)
    announce('')
    expect(synth).not.toHaveBeenCalled()
  })
})
