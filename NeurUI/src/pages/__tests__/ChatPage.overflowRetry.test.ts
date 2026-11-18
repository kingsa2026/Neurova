/**
 * QwenPaw 对照批 C2/C3 的前端适配契约。
 *
 * 后端两处新事件都复用既有 SSE `retry` 通道：
 * - C2：Anthropic 环流内切换（phase=switched，reset）——OpenAI 环既有形态；
 * - C3：管线溢出兜底重试（phase=overflow_retry，reset）——本批新相位。
 * 与 ChatPage.upstreamSilence.test.ts 同一取舍（ChatPage 体量过大不便整体
 * 挂载），锁四件"后端改了前端不会报红"的事：
 * 1. retry 事件的 reset 语义：半截 content/reasoning/steps 必须清空（两批共用的协议）；
 * 2. retryNoticeText 必须有 overflow_retry 分支——否则落进"全部耗尽"兜底文案（误标）；
 * 3. phase 联合类型含 'overflow_retry'（写漏则分支恒不成立且 tsc 不报）；
 * 4. 文案键 chat.retryOverflowRetry 11 语言齐平（一致性守卫只查互等，不查写错）。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const source = readFileSync(resolve(process.cwd(), 'src/pages/ChatPage.vue'), 'utf-8')
const types = readFileSync(resolve(process.cwd(), 'src/types/chat.ts'), 'utf-8')

const LOCALES = [
  'zh-CN', 'en-US', 'ja-JP', 'ko-KR', 'de-DE', 'es-ES',
  'fr-FR', 'it-IT', 'ru-RU', 'ar-SA', 'hi-IN',
]

function blockAfter(anchor: string, haystack: string = source): string {
  const idx = haystack.indexOf(anchor)
  if (idx === -1) return ''
  const braceStart = haystack.indexOf('{', idx)
  if (braceStart === -1) return ''
  let depth = 0
  for (let i = braceStart; i < haystack.length; i++) {
    if (haystack[i] === '{') depth++
    else if (haystack[i] === '}') {
      depth--
      if (depth === 0) return haystack.slice(braceStart + 1, i)
    }
  }
  return ''
}

describe('C2/C3 retry 事件 reset 语义', () => {
  const retryCase = blockAfter("case 'retry': {")

  it('reset 到达即清空半截 content/reasoning/steps（防两模型/两轮拼接）', () => {
    expect(retryCase).not.toBe('')
    expect(retryCase).toContain('if (event.reset)')
    expect(retryCase).toContain('msg.content = ')
    expect(retryCase).toContain('msg.reasoning = ')
    expect(retryCase).toContain('msg.steps = ')
  })
})

describe('C3 overflow_retry 相位文案', () => {
  const noticeText = blockAfter('function retryNoticeText(msg: ChatMessage): string {')

  it('retryNoticeText 有 overflow_retry 分支并取 chat.retryOverflowRetry', () => {
    expect(noticeText).toContain("n.phase === 'overflow_retry'")
    expect(noticeText).toContain("t('chat.retryOverflowRetry'")
  })

  it('phase 联合类型含 overflow_retry（写漏时分支恒不成立且 tsc 不报）', () => {
    const phaseLine = types.split('\n').find((ln) => ln.includes("phase: 'waiting'")) ?? ''
    expect(phaseLine).toContain("'overflow_retry'")
  })

  it.each(LOCALES)('%s 有 chat.retryOverflowRetry 文案', (locale) => {
    const file = readFileSync(
      resolve(process.cwd(), `src/i18n/locales/${locale}.ts`),
      'utf-8',
    )
    const line = file.split('\n').find((ln) => ln.includes('retryOverflowRetry:')) ?? ''
    expect(line).not.toBe('')
  })
})
