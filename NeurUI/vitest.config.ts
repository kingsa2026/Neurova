import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
    },
  },
  test: {
    globals: true,
    // console 输出不经过 worker→主进程的 RPC 桥接（Issue #88）。
    //
    // 根因：worker 侧 createSafeRpc 把每次 console 桥接登记进 pending 集合，
    // execute() 的 finally 里 rpcDone() 只对「快照到的」pending 做 await；
    // 而 console 的发送经 queueMicrotask 调度，快照与发送之间存在窗口——
    // 窗口内新登记的桥接 promise 不在快照里，随即被 rpc.$rejectPendingCalls
    // 判为 EnvironmentTeardownError（"Closing rpc while onUserConsoleLog
    // was pending"）上报为 Unhandled Rejection，用例全绿但进程退出码为 1。
    // 该窗口是竞态，与哪个测试文件产出 console 无关：CI 报的归属文件在多次
    // 运行间会变（本仓实测 AgentListPage.package.test.ts / UsageStatsPage.test.ts）。
    //
    // 修法：测试运行期直接走原生 console，桥接面归零，窗口随之消失。
    // 代价是 reporter 不再聚合 console；本仓无任何测试断言 console 聚合结果。
    disableConsoleIntercept: true,
    environment: 'jsdom',
    setupFiles: ['./src/test-setup.ts'],
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'html'],
      // P1-8：coverage 阈值起步线（lines 30，随测试补齐逐步上调）
      thresholds: {
        lines: 30,
        functions: 25,
        statements: 30,
      },
    },
  },
})
