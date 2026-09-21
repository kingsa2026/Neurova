/**
 * vitest console 桥接竞态守卫（CI 常驻，Issue #88）。
 *
 * 背景：2026-09-21 cnb 构建 cnb-8to-1k321sp8q#007（frontend → unit tests
 * (vitest)）失败，用例层面 221 文件 / 1824 用例全绿，进程退出码却是 1：
 *
 *   Vitest caught 1 unhandled error during the test run.
 *   Unhandled Rejection
 *   EnvironmentTeardownError: [vitest-worker]: Closing rpc while
 *     "onUserConsoleLog" was pending
 *   This error originated in "src/pages/__tests__/AgentListPage.package.test.ts"
 *
 * 根因（vitest 4.1.11 worker 侧真实缺陷，非本仓测试写法问题）：
 *   1. createSafeRpc 把每次 console 桥接的 promise 登记进模块级 pending 集合；
 *   2. execute() 的 finally 调用 rpcDone()，它只 await **快照时刻**的 pending；
 *   3. 而 console 发送经 queueMicrotask 调度，快照与登记之间存在窗口；
 *   4. 窗口内新登记的 promise 不在快照里，紧接着被 rpc.$rejectPendingCalls
 *      判为 EnvironmentTeardownError 并作为 Unhandled Rejection 上报。
 *   该窗口是竞态，与「哪个文件产出 console」无关——同一次失败里被点名的归属
 *   文件随运行变化（本仓复核实测 AgentListPage.package.test.ts 与
 *   UsageStatsPage.test.ts 都会出现）。
 *
 * 契约：vitest.config.ts 必须保持 disableConsoleIntercept: true，
 * 让测试期 console 走原生实现、桥接面归零，窗口不复存在。
 * 放宽/删除该开关 = #88 的偶发红会原样回来，且用例依旧全绿、难以察觉。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

const CONFIG = join(process.cwd(), 'vitest.config.ts')

describe('vitest console 桥接竞态守卫（Issue #88）', () => {
  it('vitest.config.ts 保持 disableConsoleIntercept: true', () => {
    const source = readFileSync(CONFIG, 'utf-8')
    // 允许 `disableConsoleIntercept: true` 形态，拒绝注释掉的假接线
    const active = source
      .split('\n')
      .filter((line) => !line.trim().startsWith('//'))
      .join('\n')
    expect(
      /disableConsoleIntercept\s*:\s*true\b/.test(active),
      'disableConsoleIntercept: true 缺失或被注释——worker→主进程 console 桥接'
        + '恢复后，EnvironmentTeardownError 竞态（Issue #88）会重新偶发，'
        + '且体现为「用例全绿但退出码 1」，极难定位。',
    ).toBe(true)
  })
})
