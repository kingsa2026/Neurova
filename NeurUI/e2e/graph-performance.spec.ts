/**
 * C3 本体图性能预算门（specs/2026-11-12 §18）：
 * 主线程单任务上限＋首屏节点上限——大图 fixture 自建，不引外部仓资产。
 *
 * 真模块真测量：主线程预算在 Chromium 页面上下文里动态 import 真实的
 * forceLayout 模块（vite dev server 同源模块图），测的是浏览器主线程上
 * 一次真实布局收敛的耗时，不是替身。节点预算判据与页面共用 perfBudget
 * 单源（页面警示与门禁同口径，不留悬空常量）。
 */
import { test, expect } from '@playwright/test'
import {
  MAIN_TASK_BUDGET_MS,
  NODE_BUDGET,
  withinNodeBudget,
} from '../src/pages/graph-workbench/perfBudget'

const FORCE_LAYOUT_MODULE = '/src/pages/graph-workbench/forceLayout.ts'

test.describe('forceLayout performance budget (specs/2026-11-12 C3)', () => {
  test('500-node layout converges within main-thread budget', async ({ page }) => {
    await page.goto('/')
    const elapsedMs = await page.evaluate(async (moduleUrl) => {
      // 动态 import 真模块（vite 同源模块图）；import 时长不计入预算——
      // 预算量的是主线程上一次布局收敛本身。
      const mod = (await import(/* @vite-ignore */ moduleUrl)) as {
        forceLayout: (
          nodes: Array<{ id: string; label: string; type: string }>,
          edges: Array<{ source: string; target: string }>,
          rootId?: string,
        ) => Map<string, { x: number; y: number }>
      }
      const nodes = Array.from({ length: 500 }, (_, i) => ({
        id: `n${i}`, label: `Node ${i}`, type: 'concept',
      }))
      const edges = Array.from({ length: 500 }, (_, i) => ({
        source: `n${i}`, target: `n${(i + 1) % 500}`,
      }))
      const start = performance.now()
      const positions = mod.forceLayout(nodes, edges)
      const elapsed = performance.now() - start
      if (positions.size !== nodes.length) {
        throw new Error(`layout lost nodes: ${positions.size}/${nodes.length}`)
      }
      return elapsed
    }, FORCE_LAYOUT_MODULE)
    expect(elapsedMs).toBeLessThan(MAIN_TASK_BUDGET_MS)
  })

  test('node budget guard matches shared contract', async ({ page }) => {
    // 首屏节点上限：超预算触发分级呈现（页面警示与 e2e 同源 perfBudget）
    await page.goto('/')
    expect(NODE_BUDGET).toBe(500)
    expect(withinNodeBudget(NODE_BUDGET)).toBe(true)
    expect(withinNodeBudget(NODE_BUDGET + 1)).toBe(false)
  })
})
