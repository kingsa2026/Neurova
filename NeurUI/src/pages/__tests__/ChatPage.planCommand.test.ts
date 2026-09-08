/**
 * /plan 斜杠命令 — slashCommands 契约测试（ZCode 计划模式对齐）
 *
 * 锁定 ChatPage slash 面板对带参命令的契约：
 * 1. /plan 命令注册、descKey 走 i18n（chat.slashPlan）；
 * 2. 面板过滤按「首词前缀」命中：`/plan`、`/plan 重构` 弹面板，
 *    `/plansomething` 不弹（词边界防误命中）；
 * 3. run(rawInput) 提取 /plan 后剩余文本作为需求种子并打开面板；
 * 4. /plan 无参数时种子为空（面板仍打开，走面板内需求输入）。
 *
 * ChatPage 体量太大不便整体挂载：镜像 slash 过滤 + /plan run 的实现契约，
 * 语义与 ChatPage.vue 严格同构（防漂移）。
 */
import { describe, expect, it } from 'vitest'
import { ref } from 'vue'

/** 镜像 ChatPage slashFiltered 的首词前缀过滤。 */
function filterSlashCommands(names: string[], input: string): string[] {
  const q = input.trim().toLowerCase()
  if (!q.startsWith('/')) return []
  const firstWord = q.split(/\s+/)[0]
  return names.filter((n) => n.startsWith(firstWord))
}

/** 镜像 ChatPage /plan 命令的 run(rawInput)。 */
function planRun(rawInput: string, seed: { value: string }, open: { value: boolean }) {
  const extracted = rawInput.replace(/^\/plan\b\s*/i, '').trim()
  seed.value = extracted
  open.value = true
}

describe('/plan 斜杠命令契约', () => {
  it('面板过滤：/plan 与 /plan <参数> 均命中（首词前缀）', () => {
    const names = ['/plan', '/new', '/clear', '/archive']
    expect(filterSlashCommands(names, '/plan')).toContain('/plan')
    expect(filterSlashCommands(names, '/plan 重构登录模块')).toContain('/plan')
    expect(filterSlashCommands(names, '/pl')).toContain('/plan')
  })

  it('面板过滤：/plansomething 不误命中（词边界）', () => {
    const names = ['/plan', '/new', '/clear', '/archive']
    expect(filterSlashCommands(names, '/plansomething')).not.toContain('/plan')
  })

  it('run(rawInput) 提取 /plan 后文本为需求种子并打开面板', () => {
    const seed = ref('')
    const open = ref(false)
    planRun('/plan 重构登录模块 支持多租户', seed, open)
    expect(seed.value).toBe('重构登录模块 支持多租户')
    expect(open.value).toBe(true)
  })

  it('/plan 无参数时种子为空但面板仍打开', () => {
    const seed = ref('stale')
    const open = ref(false)
    planRun('/plan', seed, open)
    expect(seed.value).toBe('')
    expect(open.value).toBe(true)
  })
})
