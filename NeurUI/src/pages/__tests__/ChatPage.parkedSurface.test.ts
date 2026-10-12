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

/**
 * P3-14（§6-72 第五格）：刷新后「这条正等人续跑」的入口必须还能出现。
 *
 * SSE 是一次性的，`parked` 事件随连接消失，而 run_id 是唯一续跑凭据。后端读面
 * （`GET /console/chat/runs`）早就备好、docstring 承诺的就是"刷新或重启后必须还能查到"，
 * 缺的只有这个消费者。形态判定：闸判发生在 `agent.chat` **之前**，那轮的用户问句与
 * 助手回复都不曾落盘——历史里没有属于它的气泡，所以只能挂会话级入口，贴到上一条
 * 已完成回复上等于把续跑按钮安在另一轮头上。
 */
describe('刷新后恢复挂起回合入口（P3-14）', () => {
  const load = blockAfter('async function loadParkedRuns(')
  const resumeEntry = blockAfter('async function resumeParkedRun(')

  it('取回路径走共享 api 客户端打后端那条 run 读面', () => {
    expect(load).not.toBe('')
    expect(load).toContain("api.get('/console/chat/runs'")
    expect(load).toContain('session_id')
    // 不另造第二条请求链：裸 fetch 会绕过 401 单飞刷新与 Request-ID
    expect(load).not.toContain('fetch(')
  })

  it('只认 parked 状态的行，且 run_id 缺失的行不进列表', () => {
    expect(load).toContain("r?.status === 'parked'")
    expect(load).toContain('r?.run_id')
  })

  it('入口挂在会话级列表上，而不是贴到某条既有气泡', () => {
    expect(resumeEntry).not.toBe('')
    expect(source).toContain('v-for="run in parkedRuns"')
    expect(resumeEntry).not.toContain('.find((m)')
  })

  it('续跑复用既有那一份实现，不另起第二条流', () => {
    expect(resumeEntry).toContain('resumeParkedTurn(msg)')
    expect(resumeEntry).not.toContain('/console/chat/resume')
  })

  it('挂在 currentSessionId 的 watch 上：首会话是异步选中的，只写 onMounted 会漏', () => {
    expect(source).toMatch(/currentSessionId,[\s\S]{0,600}loadParkedRuns\(sid\)/)
  })

  it('切会话先清空，过期响应不写当前视图', () => {
    expect(load).toContain('parkedRuns.value = []')
    expect(load).toContain('currentSessionId.value !== sid')
  })

  it('取不回时点名留痕，不静默缺席一个点了没反应的入口', () => {
    expect(load).toContain('console.error')
  })

  it('不自己解析 SSE 帧（复用同一条解析口）', () => {
    expect(load).not.toBe('')
    expect(load).not.toContain('getReader()')
    expect(resumeEntry).not.toContain('getReader()')
  })
})
