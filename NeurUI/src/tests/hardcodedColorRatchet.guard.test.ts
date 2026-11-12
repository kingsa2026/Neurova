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
 *
 * 口径精化（2026-11-13 第二批）：`var(--token, fallback)` 里的兜底字面量
 * **不算硬编码**——令牌缺省时才生效，兜底是本仓"皮带加背带"的防御形态
 * （ContextUsageIndicator 全文即此形态，21 处里 14 处是兜底）。
 */
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

const COLOR_RE = /#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\)/g

const BASELINES: Record<string, number> = {
  'src/pages/ModelPage.vue': 86,  // 中性灰阶已入 ramp（#8a8a92/#d6d6de）；余为供应商品牌色与 alpha 淡色
  'src/pages/analytics/TokenActivitySection.vue': 20,  // 轴标签灰阶已入 ramp；余为数据系列色与系列渐变（可视化合法形态）
  'src/components/chat/ContextUsageIndicator.vue': 7,  // 图表段色（数据系列，合法字面量）
  'src/pages/graph-workbench/GraphExplorer3D.vue': 16,  // 3D 数据可视化色（Three.js 材质，不走 CSS 令牌）
  'src/modules/collaboration/CanvasDesignerPage.vue': 23,  // 白色 alpha 与靛蓝淡色待软底令牌
}

function countHardcodedColors(relPath: string): number {
  // 口径精化：先剥 var(..., fallback) 兜底字面量（随令牌缺省才生效，不算硬编码）
  const src = readFileSync(join(process.cwd(), relPath), 'utf-8').replace(
    /var\([^)]*\)/g,
    'var()',
  )
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
