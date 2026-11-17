/**
 * S6 自动压缩轻提示面契约（源级，与 ChatPage.upstreamSilence 同一取舍）。
 *
 * 后端压缩纪律（S6）经 console 桥 upstream_status 透传 phase=context_compacted
 * 通知（含 cutoffIndex/foldedCount/tokensBefore/tokensAfter/summary），前端此前
 * 只认 silence 相位——压缩通知会被误写成"上游静默"提示条并留在气泡上不散。
 * 本档锁住四件"后端改了前端不会报红"的事：
 * 1. SSE `upstream_status` 的 context_compacted 相位必须被认领为压缩轻提示，
 *    不落 silence 分支；
 * 2. 轻提示载荷取后端读数（foldedCount/tokensBefore/tokensAfter），不自造；
 * 3. 类型面 compactNotice 字段真实存在（联合写漏是静默的）；
 * 4. 文案键真实存在且 11 语言齐平、占位符与后端载荷对齐。
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

describe('S6 upstream_status 压缩分支', () => {
  const statusCase = blockAfter("case 'upstream_status': {")

  it('分支认领 phase=context_compacted（压缩不再误入静默提示条）', () => {
    expect(statusCase).not.toBe('')
    expect(statusCase).toContain("event.phase === 'context_compacted'")
  })

  it('压缩分支写 msg.compactNotice 且不写 silence 提示条', () => {
    expect(statusCase).toContain('msg.compactNotice = {')
    // compactNotice 分支（在 silence 赋值之前出现）不得含 phase: 'silence'
    const compactBranch = statusCase.slice(0, statusCase.indexOf("msg.compactNotice = {") + 400)
    expect(compactBranch).not.toContain("phase: 'silence'")
  })

  it('载荷取后端读数（foldedCount/tokensBefore/tokensAfter），不自造', () => {
    expect(statusCase).toContain('event.foldedCount')
    expect(statusCase).toContain('event.tokensBefore')
    expect(statusCase).toContain('event.tokensAfter')
  })
})

describe('S6 轻提示渲染与类型面', () => {
  it('模板渲染 nr-compact-notice 且文案键取 chat.contextCompactedNotice', () => {
    expect(source).toContain('nr-compact-notice')
    expect(source).toContain("t('chat.contextCompactedNotice'")
  })

  it('ChatMessage 类型含 compactNotice 字段（foldedCount/tokensBefore/tokensAfter/reason）', () => {
    expect(types).toContain('compactNotice?')
    expect(types).toContain('foldedCount')
    expect(types).toContain('tokensBefore')
    expect(types).toContain('tokensAfter')
    expect(types).toContain('reason')
  })

  it.each(LOCALES)('%s 有 chat.contextCompactedNotice 且带 {folded}/{before}/{after} 插值', (locale) => {
    const file = readFileSync(resolve(process.cwd(), `src/i18n/locales/${locale}.ts`), 'utf-8')
    const line = file.split('\n').find((ln) => ln.includes('contextCompactedNotice:')) ?? ''
    expect(line).not.toBe('')
    expect(line).toContain('{folded}')
    expect(line).toContain('{before}')
    expect(line).toContain('{after}')
  })
})
