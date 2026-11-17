/**
 * S1-1E 多 agent 基线报告只读面契约
 *
 * 后端 GET /benchmark/baseline-reports（列表，新→旧）与
 * GET /benchmark/baseline-reports/{report_id}（单份全文）已存在
 * （neurova/api/endpoints/benchmark.py，读 runner 落盘报告，不建第二套存储）。
 * 本档锁 URL 形态、信封解包与 usage/轨迹字段边界——前端模块此前未封装这两个
 * 端点（BenchmarkPage 无基线报告视图），契约先行立红再补实现。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('@/api', () => ({
  default: {
    get: vi.fn().mockResolvedValue({ code: 0, message: 'success', data: {} }),
    post: vi.fn().mockResolvedValue({ code: 0, data: {} }),
    put: vi.fn().mockResolvedValue({ code: 0, data: {} }),
    delete: vi.fn().mockResolvedValue({ code: 0, data: {} }),
  },
}))

import api from '@/api'
import { getBaselineReports, getBaselineReport } from '@/api/modules/benchmark'

const mockGet = vi.mocked(api.get)

beforeEach(() => {
  vi.clearAllMocks()
})

describe('基线报告列表契约', () => {
  it('GET /benchmark/baseline-reports（只读，无查询参数）', async () => {
    await getBaselineReports()
    expect(mockGet).toHaveBeenCalledTimes(1)
    expect(mockGet).toHaveBeenCalledWith('/benchmark/baseline-reports')
  })

  it('data.items 为报告清单（新→旧），行含隔离注记与模式聚合列', async () => {
    const items = [
      {
        report_id: 'bench-20261117T120000Z-abc123',
        generated_at: '2026-11-17T12:00:00+00:00',
        task_isolated_memory: true,
        task_count: 13,
        metrics: {
          swarm: { task_count: 13, passed_count: 3, success_rate: 0.2308, total_tokens: 120000, total_steps: 40, total_tool_calls: 18 },
          solo: { task_count: 13, passed_count: 1, success_rate: 0.0769, total_tokens: 30000, total_steps: 13, total_tool_calls: 2 },
        },
        comparison: { available: true, token_multiplier: 4.0 },
      },
    ]
    mockGet.mockResolvedValueOnce({ code: 0, message: 'success', data: { items, total: 1 } })
    const resp: any = await getBaselineReports()
    expect(resp.code).toBe(0)
    expect(resp.data.items[0].report_id).toBe('bench-20261117T120000Z-abc123')
    expect(resp.data.items[0].metrics.swarm.total_tool_calls).toBe(18)
    expect(resp.data.items[0].task_isolated_memory).toBe(true)
  })
})

describe('单份报告全文契约', () => {
  it('GET /benchmark/baseline-reports/{report_id}（reportId 原样进路径）', async () => {
    await getBaselineReport('bench-20261117T120000Z-abc123')
    expect(mockGet).toHaveBeenCalledTimes(1)
    expect(mockGet).toHaveBeenCalledWith('/benchmark/baseline-reports/bench-20261117T120000Z-abc123')
  })

  it('逐任务行含 usage（prompt/completion/total tokens、steps、toolCalls）与轨迹列', async () => {
    const report = {
      generated_at: '2026-11-17T12:00:00+00:00',
      task_isolated_memory: true,
      metrics: {},
      comparison: {},
      tasks: [
        {
          task_id: 'T2-handoff',
          mode: 'swarm',
          passed: true,
          score: 1,
          elapsed_seconds: 12.4,
          usage: {
            promptTokens: 4200,
            completionTokens: 380,
            totalTokens: 4580,
            elapsedSeconds: 12.4,
            steps: 3,
            toolCalls: 2,
          },
          trajectory: { toolsUsed: ['memory_search', 'handoff'], source: 'tool_messages' },
        },
      ],
    }
    mockGet.mockResolvedValueOnce({ code: 0, message: 'success', data: report })
    const resp: any = await getBaselineReport('bench-x')
    const task = resp.data.tasks[0]
    expect(task.usage.totalTokens).toBe(4580)
    expect(task.usage.promptTokens).toBe(4200)
    expect(task.usage.completionTokens).toBe(380)
    expect(task.usage.steps).toBe(3)
    expect(task.usage.toolCalls).toBe(2)
    expect(task.trajectory.toolsUsed).toEqual(['memory_search', 'handoff'])
  })
})
