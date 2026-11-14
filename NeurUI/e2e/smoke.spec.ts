/**
 * P2-12 冒烟 e2e：真浏览器加载应用壳——页面渲染、无致命错误浮层。
 *
 * 与 graph-performance.spec.ts 同一 webServer（vite dev, 8100）；后端缺席时
 * 应用应降级渲染而非白屏/崩溃（冒烟判据：根节点有内容 + 无 Vite 错误浮层）。
 */
import { test, expect } from '@playwright/test'

test.describe('应用壳冒烟（P2-12）', () => {
  test('根节点渲染且有内容', async ({ page }) => {
    await page.goto('/')
    const app = page.locator('#app')
    await expect(app).toBeVisible()
    const contentLength = await app.evaluate((node) => (node.textContent || '').trim().length)
    expect(contentLength).toBeGreaterThan(0)
  })

  test('无未捕获异常浮层', async ({ page }) => {
    const pageErrors: string[] = []
    page.on('pageerror', (err) => pageErrors.push(String(err)))
    await page.goto('/')
    // vite 错误浮层（如出现）意味着模块图编译/运行失败
    const overlay = page.locator('vite-error-overlay')
    await page.waitForTimeout(1500)
    expect(await overlay.count()).toBe(0)
    expect(pageErrors).toEqual([])
  })
})
