/**
 * 技能行主键归一单点契约（2026-10-24）
 *
 * 根因背景：后端四个技能读面（/marketplace/skills、/skill-pool/public、
 * /skill-pool/me/skills、/skill-pool/agent/{id}/skills）的行主键都是
 * `skill_id`，而前端消费方统一读 `id`。旧形态是各页在自己的取数函数里
 * 手工重命名——四处重复里 AgentSkillPage 的市场导入漏了，点「安装」即发出
 * `POST /marketplace/skills/undefined/install`（真机 404）；同一形状还潜伏在
 * AgentSchedulerPage 的技能下拉。
 *
 * 契约：`skill_id → id` 的映射只允许存在于 `src/api/modules/skill-pool.ts`
 * 一处（AGENTS.md §6 单一事实源、§7「该功能只剩一处实现被消费」）。
 * 页面不得再各自重命名——新增一处重复就等于给下一个漏掉它的页面预置故障。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, resolve } from 'node:path'

const SRC = resolve(process.cwd(), 'src')
const SINGLE_SOURCE = join(SRC, 'api', 'modules', 'skill-pool.ts').replace(/\\/g, '/')

/** 重命名惯用法的三种落笔形态（页面里出现任何一种即违例）。 */
const RENAME_IDIOMS: RegExp[] = [
  /\bid\s*:\s*[^\n]*\bskill_id\b/, //   id: s.skill_id ?? s.id
  /\bskill_id\s*\?\?[^\n]*\bid\b/, //   s.skill_id ?? s.id
  /\bid\s*\?\?[^\n]*\bskill_id\b/, //   s.id ?? s.skill_id
]

/** 生产码（.vue / .ts），排除判据自身与测试目录。 */
function collectProductionFiles(dir: string): string[] {
  const out: string[] = []
  for (const name of readdirSync(dir)) {
    const full = join(dir, name)
    if (statSync(full).isDirectory()) {
      if (name === '__tests__' || name === 'node_modules') continue
      out.push(...collectProductionFiles(full))
      continue
    }
    if (!/\.(vue|ts)$/.test(name)) continue
    if (name.endsWith('.test.ts') || name.endsWith('.spec.ts')) continue
    out.push(full)
  }
  return out
}

function findOffenders(): string[] {
  const offenders: string[] = []
  for (const file of collectProductionFiles(SRC)) {
    const rel = file.replace(/\\/g, '/')
    if (rel === SINGLE_SOURCE) continue
    // 只剔整行 // 注释。不做 /* */ 块剔除：.vue 模板里的 HTML 注释含 `/*.json`
    // 这类字面量，非贪婪块正则会一路吞到下一个 `*/`，把中间的代码整段抹掉
    // ——实测把 AgentSkillPage.vue 的归一现场吞成"无违例"，判据当场失明。
    const body = readFileSync(file, 'utf-8').replace(/^\s*\/\/.*$/gm, '')
    if (RENAME_IDIOMS.some((re) => re.test(body))) offenders.push(rel)
  }
  return offenders
}

describe('技能行 skill_id→id 归一只在 API 边界一处（禁止各页重命名）', () => {
  it('正向控制：三条惯用法正则各自咬得住合成样本（否则本守卫恒绿）', () => {
    const samples = [
      'return arr.map((s: any) => ({ ...s, id: s.skill_id ?? s.id }))',
      'const key = row.skill_id ?? row.id',
      'const shown = row.id ?? row.skill_id',
    ]
    samples.forEach((sample, i) => {
      expect(RENAME_IDIOMS.some((re) => re.test(sample)),
        `合成违例样本 ${i + 1} 未被任何一条正则命中，正则已失效：\n${sample}`).toBe(true)
    })
  })

  it('反向控制：除 skill_id 之外的普通字段名不得被误判为违例', () => {
    const innocent = 'const payload = { skill_id: skill.id, version: skill.version }'
    expect(RENAME_IDIOMS.some((re) => re.test(innocent))).toBe(false)
  })

  it('单源确实存在：skill-pool.ts 自身带 skill_id→id 归一（整段被删即红）', () => {
    const body = readFileSync(SINGLE_SOURCE, 'utf-8')
    expect(body).toMatch(/\bskill_id\s*\?\?[^\n]*\bid\b/)
  })

  it('全仓生产码无第二处重命名（预筛须真扫到四个消费页，防路径基准漂移导致空扫恒绿）', () => {
    const scanned = collectProductionFiles(SRC).map((f) => f.replace(/\\/g, '/'))
    expect(scanned.length).toBeGreaterThan(50)
    const consumers = scanned.filter((f) =>
      /pages\/(AgentSkillPage|SkillMarketPage|SkillPoolPage|AgentSchedulerPage)\.vue$/.test(f))
    expect(consumers, `扫面没够到已知消费页，路径基准已漂移：\n${consumers.join('\n')}`).toHaveLength(4)
    const offenders = findOffenders()
    expect(offenders, `以下页面仍在各自重命名 skill_id→id：\n${offenders.join('\n')}`).toEqual([])
  })
})
