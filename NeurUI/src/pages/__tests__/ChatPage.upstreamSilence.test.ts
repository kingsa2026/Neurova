/**
 * ChatPage 上游静默面契约（§6-397 批 C）。
 *
 * 与 ChatPage.parkedSurface.test.ts 同一取舍（ChatPage 体量过大不便整体挂载），
 * 这里锁住四件"后端改了前端不会报红"的事：
 * 1. SSE `upstream_status` 事件必须被认领并落到提示条上——后端让出事件而前端 switch
 *    没有那一支，用户看到的还是转圈（那正是本批要修的事故体感）；
 * 2. 静默秒数**只信后端**：前端不自推倒数（它不知道最后一次收到字节是何时），
 *    所以这一支不许启本地 ticker；
 * 3. 文案键真实存在且 11 语言齐平——一致性守卫只保证各语言互等，不保证键没写错；
 * 4. 类型面的 phase 联合必须含 'silence'，否则 `retryNoticeText` 的分支永远进不去
 *    而 vue-tsc 也拦不住（联合类型收窄写漏是静默的）。
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

describe('批 C upstream_status 事件', () => {
  const statusCase = blockAfter("case 'upstream_status': {")

  it('分支存在且写入 phase=silence 的提示条（静默不再只剩转圈）', () => {
    expect(statusCase).not.toBe('')
    expect(statusCase).toContain("phase: 'silence'")
    expect(statusCase).toContain('msg.retryNotice = {')
  })

  it('秒数取自后端读数，不自推、不启本地倒数', () => {
    expect(statusCase).toContain('event.silent_seconds')
    expect(statusCase).not.toContain('startRetryTicker()')
  })
})

describe('批 C 文案与类型面', () => {
  const noticeText = blockAfter('function retryNoticeText(msg: ChatMessage): string {')

  it('retryNoticeText 有 silence 分支并取 chat.upstreamSilence', () => {
    expect(noticeText).toContain("n.phase === 'silence'")
    expect(noticeText).toContain("t('chat.upstreamSilence'")
  })

  it('phase 联合类型含 silence（写漏时分支恒不成立且 tsc 不报）', () => {
    const phaseLine = types.split('\n').find((ln) => ln.includes("phase: 'waiting'")) ?? ''
    expect(phaseLine).toContain("'silence'")
    expect(types).toContain('silentSeconds?: number')
  })

  it.each(LOCALES)('%s 有 chat.upstreamSilence 且带 {seconds} 插值', (locale) => {
    const file = readFileSync(
      resolve(process.cwd(), `src/i18n/locales/${locale}.ts`),
      'utf-8',
    )
    const line = file.split('\n').find((ln) => ln.includes('upstreamSilence:')) ?? ''
    expect(line).not.toBe('')
    expect(line).toContain('{seconds}')
  })
})
