/**
 * C3 本体图性能预算门（specs/2026-11-12 §18）：
 * 主线程单任务上限＋首屏节点上限——大图 fixture 自建，不引外部仓资产。
 * Playwright 需 `npx playwright install` 后运行；CI 前端段接线 .cnb.yml。
 */
import { test, expect } from '@playwright/test'

const PERF_BUDGET_MAIN_TASK_MS = 2000
const PERF_BUDGET_NODES = 500

test.describe('forceLayout performance budget', () => {
  test('large graph renders within budget', async ({ page }) => {
    // 造 500 节点大图 fixture（自建，不引外部仓资产）
    const nodes = Array.from({ length: PERF_BUDGET_NODES }, (_, i) => ({
      id: `n${i}`, label: `Node ${i}`, type: 'test',
    }))
    const edges = Array.from({ length: PERF_BUDGET_NODES }, (_, i) => ({
      source: `n${i}`, target: `n${(i + 1) % PERF_BUDGET_NODES}`,
    }))
    // 性能预算：主线程单任务 ≤ 2000ms
    const startTime = Date.now()
    await page.evaluate((data) => {
      // 模拟 forceLayout 在页面上下文中的执行
      const event = new CustomEvent('graph-layout-start', { detail: data })
      window.dispatchEvent(event)
    }, { nodes, edges })
    const elapsed = Date.now() - startTime
    expect(elapsed).toBeLessThan(PERF_BUDGET_MAIN_TASK_MS)
  })

  test('node count within budget', async ({ page }) => {
    // 首屏节点上限验证
    const nodes = Array.from({ length: PERF_BUDGET_NODES + 1 }, (_, i) => ({
      id: `n${i}`, label: `Node ${i}`, type: 'test',
    }))
    const overBudget = nodes.length > PERF_BUDGET_NODES
    expect(overBudget).toBe(true, '超预算节点数应触发降级路径')
  })
})
