/**
 * ChatPage 挂起面契约（P2-8 第二批）。
 *
 * 与 ChatPage.planCommand.test.ts 同一取舍：ChatPage 体量过大不便整体挂载，
 * 这里以源码契约锁住三件真会静默坏掉的事：
 * 1. `parked` 事件没有 run_id 时必须**点名失败**——留一个点了没反应的"已挂起"
 *    标签，就是本仓反复在修的那类假成功。
 * 2. SSE 解析只允许一份（续跑流与主流共用）；写第二份时后端改帧法只会坏掉一半。
 * 3. 用到的 i18n key 真实存在——11 语言一致性守卫只保证各语言互等，
 *    不保证这个 key 根本没写错过。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const source = readFileSync(resolve(process.cwd(), 'src/pages/ChatPage.vue'), 'utf-8')

function blockAfter(anchor: string): string {
  const idx = source.indexOf(anchor)
  if (idx === -1) return ''
  const braceStart = source.indexOf('{', idx)
  if (braceStart === -1) return ''
  let depth = 0
  for (let i = braceStart; i < source.length; i++) {
    if (source[i] === '{') depth++
    else if (source[i] === '}') {
      depth--
      if (depth === 0) return source.slice(braceStart + 1, i)
    }
  }
  return ''
}

describe('P2-8 parked 事件', () => {
  const parkedCase = blockAfter("case 'parked': {")

  it('parked 分支存在且写入 parkedNotice（含续跑凭据 runId）', () => {
    expect(parkedCase).not.toBe('')
    expect(parkedCase).toContain('msg.parkedNotice = {')
    expect(parkedCase).toContain('runId')
    // 挂起即收尾：不能在 parked 之后还留着"正在输出"的假象
    expect(parkedCase).toContain('msg.streaming = false')
  })

  it('缺 run_id 时点名失败并跳出，而不是渲染一个点了没反应的挂起标签', () => {
    const branch = blockAfter('if (!runId) {')
    expect(branch).not.toBe('')
    expect(branch).toContain('break')
    expect(branch).not.toContain('parkedNotice')
  })
})

describe('P2-8 SSE 解析单源', () => {
  it('解析器定义恰好一处', () => {
    const defs = source.match(/async function\* sseJsonEvents\(/g) ?? []
    expect(defs).toHaveLength(1)
  })

  it('主流与续跑流共用同一个解析器（没有第二份 while/reader 循环）', () => {
    const read = blockAfter('const readStream = async')
    const resume = blockAfter('async function resumeParkedTurn(')
    expect(read).toContain('sseJsonEvents(response)')
    expect(resume).toContain('sseJsonEvents(response)')
    expect(resume).not.toBe('')
    expect(read).not.toContain('response.body?.getReader()')
    expect(resume).not.toContain('response.body?.getReader()')
  })
})

describe('P2-8 挂起面用到的 i18n key 真实存在', () => {
  const keys = ['turnParked', 'resumeRun', 'resumeFailed', 'parkedMissingRunId', 'retryYieldWait']

  for (const key of keys) {
    it(`zh-CN 与 en-US 都定义了 chat.${key}`, () => {
      for (const locale of ['zh-CN', 'en-US']) {
        const text = readFileSync(
          resolve(process.cwd(), `src/i18n/locales/${locale}.ts`),
          'utf-8',
        )
        expect(new RegExp(`^\\s+${key}:`, 'm').test(text)).toBe(true)
      }
    })
  }

  it('模板里真的把挂起态渲染成了可见可点的界面', () => {
    expect(source).toContain('v-if="msg.parkedNotice"')
    expect(source).toContain('@click="resumeParkedTurn(msg)"')
  })
})
