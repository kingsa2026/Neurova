/**
 * 跨文件同名函数盘点守卫（Issue #192 收口）。
 *
 * 事故：Issue #192 的收口评论登记过一条「全仓另有 91 组同名函数……未强行合并」
 * 的待办。口头数字有三重问题——口径未落盘（不可复跑）、分类未做（真重复与
 * 语义各异混在一个数里）、结论未接线（后人无从判断该不该动）。
 *
 * 本守卫把口径与结论钉死，事实源只有两处：
 *   1. `scripts-qa/duplicate-function-audit.mjs` —— 口径与分档的唯一实现；
 *   2. `docs/05-reports/同名函数盘点台账_2026-09-25.md` —— 机器段由脚本生成。
 * 台账机器段与脚本实跑结果不一致即判红（禁止手抄第二份清单，修复教义第 6 条）。
 *
 * 三条判据：
 *   A. A 类（同名同体·无局部耦合）必须为空 —— 真重复一律收口到单一属主，
 *      否则两侧独立演进必然漂移（前例：removePendingFile 少了可选链抛 TypeError）；
 *   B. 台账机器段的 B/C 两组分组与文件清单必须与实跑结果逐组相等；
 *   C. C 类（同名异体）不得被"按名合并"成一个 —— 逐组锁住体数不降级。
 */
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import {
  LEDGER_BEGIN,
  LEDGER_END,
  auditDuplicateFunctions,
  inventoryPayload,
  renderLedgerBlock,
} from '../../scripts-qa/duplicate-function-audit.mjs'

const LEDGER_PATH = join(
  process.cwd(),
  '..',
  'docs',
  '05-reports',
  '同名函数盘点台账_2026-09-25.md',
)

function readLedger(): string {
  return readFileSync(LEDGER_PATH, 'utf-8')
}

describe('跨文件同名函数盘点', () => {
  it('A 类（同名同体·无局部耦合）已清零，真重复全部收口到单一属主', () => {
    const { tiers } = auditDuplicateFunctions()
    const remaining = tiers.A.map((group) => `${group.name} → ${group.sites.join(' , ')}`)
    expect(
      remaining,
      `以下同名同体函数仍在多处各留一份定义（各自漂移的起点），须收口到单一属主:\n${remaining.join('\n')}`,
    ).toEqual([])
  })

  it('台账机器段与实跑结果逐组相等（台账是生成物，不是手抄件）', () => {
    const expected = renderLedgerBlock()
    const ledger = readLedger()
    const begin = ledger.indexOf(LEDGER_BEGIN)
    const end = ledger.indexOf(LEDGER_END)
    expect(begin, '台账缺少机器段起始标记').toBeGreaterThan(-1)
    expect(end, '台账缺少机器段结束标记').toBeGreaterThan(begin)
    const actual = ledger.slice(begin, end + LEDGER_END.length)
    expect(
      actual,
      '台账机器段与实跑口径不一致：请重跑 node scripts-qa/duplicate-function-audit.mjs --write-ledger <台账>',
    ).toBe(expected)
  })

  it('B/C 两组在台账里有逐组处置行，不停留在「未强行合并」一句口头话', () => {
    const report = auditDuplicateFunctions()
    const ledger = readLedger()
    const payload = inventoryPayload(report)
    const missing = [...payload.tierB, ...payload.tierC]
      .filter((group) => !ledger.includes(`| ${group.name} |`))
      .map((group) => group.name)
    expect(
      missing,
      `以下同名函数组在台账里没有处置结论行（按模块评估的结论必须逐组可见）:\n${missing.join('\n')}`,
    ).toEqual([])
  })

  it('C 类（同名异体）不得被按名强行合并：逐组锁住体数不降级', () => {
    const { tiers } = auditDuplicateFunctions()
    const collapsed = tiers.C.filter((group) => (group.variants ?? 0) < 2).map((group) => group.name)
    expect(collapsed, '同名异体的「体数」掉到 1 说明已被按名合并').toEqual([])
    // 同名异体组里，至少这几组是"同名同意图、口径不同"的高危项，必须保留差异
    const hazardous = ['formatDate', 'getFileIcon', 'formatTime', 'formatSize']
    for (const name of hazardous) {
      const groups = tiers.C.filter((group) => group.name === name)
      expect(groups.length, `${name} 应作为同名异体登记在 C 类`).toBe(1)
    }
  })
})
