import { defineConfig } from '@playwright/test'

/**
 * C3 性能预算门配置（specs/2026-11-12 §18）。
 * webServer 复用项目 dev 脚本（vite --port 8100 --strictPort）——同源模块图
 * 供 e2e 动态 import 真实 forceLayout；CI 中不复用既有 server。
 */
export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  fullyParallel: false,
  workers: 1,
  // P2-12：CI 侧对偶发失败重试一次（本地不重试，快速暴露问题）
  retries: process.env.CI ? 1 : 0,
  use: {
    baseURL: 'http://localhost:8100',
  },
  webServer: {
    command: 'npm run dev',
    url: 'http://localhost:8100',
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
})
