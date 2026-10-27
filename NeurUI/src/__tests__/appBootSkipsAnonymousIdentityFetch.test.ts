/**
 * boot 期不许发「注定 401」的身份请求（§6-430 遗留的「登录前空态」根因之一）
 *
 * 实测形态（真浏览器独立 profile，无任何 localStorage）：打开 /memory 时记忆页根本还没
 * 挂载，`App.vue` 的 `onMounted` 已经无条件拉过一次 `/api/v1/agents` ⇒ 401 ⇒ 拦截器清
 * 凭证并跳转。也就是说**每一个**未登录访客在**每一个**页面上都先吃一发 401，控制台里的
 * 红、以及那次「把深链覆盖成裸 /login」的跳转，都不是记忆页自己造成的。
 *
 * 处置口径：把这一枪收进「已登录」这一个门里，而且只留一处调用点——现仓在登录成功后
 * 根本没人再拉过 agents（`LoginPage`/`auth` 里查不到 `loadAgents`），所以只在 boot 拉一次
 * 的写法，对未登录访客是必然 401，对「先登录后用」这条路又是空侧栏。收成 `watch(
 * () => authStore.isAuthenticated, ..., { immediate: true })` 一处，两形同时闭合。
 *
 * 反向一格：`loadWorkflowAgents()` 打的 `/api/v1/neurflow/agents` 实测匿名 200，
 * 故意留在门外——顺手全 gate 就是把两条不同的事实说成一条。
 *
 * 形态说明：`App.vue` 挂载要整套主题与 store 夹具，本仓没有这个体量的前端先例，故这一档
 * 钉的是**代码位置**（按花括号配对算出门内门外），真链路的「未登录零 401」走活体验证。
 */
import { describe, expect, it } from 'vitest'
import rawAppSource from '@/App.vue?raw'

// 仓内 .vue 多为 CRLF；判据按行配对算门内门外，先把行尾归一，否则 marker 里的换行
// 匹配不上，「门没找到」会被读成「判据咬住了」。
const appSource = rawAppSource.replace(/\r\n/g, '\n')

/** 取 `marker` 之后第一个 `{` 的花括号配对区间（含首尾花括号）。 */
function blockSpan(src: string, marker: string): [number, number] | null {
  const head = src.indexOf(marker)
  if (head < 0) return null
  const open = src.indexOf('{', head)
  if (open < 0) return null
  let depth = 0
  for (let i = open; i < src.length; i += 1) {
    if (src[i] === '{') depth += 1
    else if (src[i] === '}') {
      depth -= 1
      if (depth === 0) return [open, i]
    }
  }
  return null
}

const BOOT = 'onMounted(() => {'
const AUTH_WATCH = 'watch(\n  () => authStore.isAuthenticated'
const BOOT_GATE = 'if (authStore.isAuthenticated)'

describe('boot 期身份请求先问登录态', () => {
  it('agents 只有唯一一处调用点（门内一处，不许留下第二枪）', () => {
    const calls = appSource.match(/agentStore\.loadAgents\(\)/g) ?? []
    expect(calls.length).toBe(1)
  })

  it('那一处落在登录态门的体内：未登录根本不发这注定 401 的一枪', () => {
    const span = blockSpan(appSource, AUTH_WATCH)
    expect(span).not.toBeNull()
    const [open, end] = span as [number, number]
    const call = appSource.indexOf('agentStore.loadAgents()', open)
    expect(call).toBeGreaterThan(open)
    expect(call).toBeLessThan(end)
  })

  it('反向：boot 的 onMounted 里不再有 agents 那一枪', () => {
    const span = blockSpan(appSource, BOOT)
    expect(span).not.toBeNull()
    expect(appSource.slice(span![0], span![1])).not.toContain('agentStore.loadAgents()')
  })

  it('那个门是 immediate 的：登录前打开也能在登录那一刻补拉成环', () => {
    const watchHead = appSource.indexOf(AUTH_WATCH)
    expect(watchHead).toBeGreaterThan(-1)
    expect(appSource.slice(watchHead, watchHead + 900)).toMatch(/immediate:\s*true/)
  })

  it('反向：匿名 200 的 loadWorkflowAgents() 仍留在 boot 里，不被顺手 gate', () => {
    const boot = blockSpan(appSource, BOOT)
    const gate = blockSpan(appSource, AUTH_WATCH)
    expect(boot && appSource.slice(boot[0], boot[1])).toContain('agentStore.loadWorkflowAgents()')
    expect(gate && appSource.slice(gate[0], gate[1])).not.toContain('agentStore.loadWorkflowAgents()')
  })

  it('既有的 fetchCurrentUser 门不许被摘（同一 onMounted 里本就问着登录态）', () => {
    const span = blockSpan(appSource, BOOT_GATE)
    expect(span).not.toBeNull()
    expect(appSource.slice(span![0], span![1])).toContain('authStore.fetchCurrentUser()')
  })
})
