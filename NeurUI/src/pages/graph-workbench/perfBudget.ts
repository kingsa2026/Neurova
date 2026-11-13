/**
 * C3 本体图性能预算（specs/2026-11-12 §18）——单源常量与判据。
 *
 * 页面分级渲染读数与 Playwright 预算门共用这一份，不许第二份口径：
 * - MAIN_TASK_BUDGET_MS：主线程单任务（一次 forceLayout 收敛）上限；
 * - NODE_BUDGET：首屏节点上限，超限走既有分级呈现（枢纽邻域优先）；
 * - withinNodeBudget：节点数判据（页面警示与 e2e 断言同源）。
 */

export const MAIN_TASK_BUDGET_MS = 2000

export const NODE_BUDGET = 500

export function withinNodeBudget(count: number): boolean {
  return count <= NODE_BUDGET
}
