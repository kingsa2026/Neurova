/**
 * P2-31 硬编码色值棘轮守卫（全库断点审计 2026-11-12）。
 *
 * 审计口径：组件层硬编码色值 200+ 处，状态色应换 var(--nr-*) 令牌、装饰色
 * 进 variables.css。全量清零是一次视觉回归风险集中的大工程，故按本仓棘轮
 * 惯例（同 promptSurfaceBudgetRatchet）：基线取落格当日现量，**只降不升**，
 * 逐批清零。新增硬编码色值即红。
 *
 * 口径（唯一）：统计文件内 `#hex` 与 `rgb(a)(...)` 字面量出现次数（含 JS 侧
 * 品牌色——它们同属"绕过主题令牌"的形态）。基线＝2026-11-12 落格现量。
 */
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

const COLOR_RE = /#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\)/g

const BASELINES: Record<string, number> = {
  'src/pages/ModelPage.vue': 114,
  'src/pages/analytics/TokenActivitySection.vue': 39,
  'src/components/chat/ContextUsageIndicator.vue': 22,
  'src/pages/graph-workbench/GraphExplorer3D.vue': 16,
  'src/modules/collaboration/CanvasDesignerPage.vue': 46,
}

function countHardcodedColors(relPath: string): number {
  const src = readFileSync(join(process.cwd(), relPath), 'utf-8')
  return (src.match(COLOR_RE) ?? []).length
}

describe('P2-31 硬编码色值棘轮（Top5 组件）', () => {
  for (const [relPath, baseline] of Object.entries(BASELINES)) {
    it(`${relPath} 硬编码色值不得高于基线 ${baseline}`, () => {
      const count = countHardcodedColors(relPath)
      expect(count, `${relPath} 新增了硬编码色值（现量 ${count} > 基线 ${baseline}）；` +
        '新增颜色请走 variables.css 令牌或既有 --nr-* 变量').toBeLessThanOrEqual(baseline)
    })
  }
})
